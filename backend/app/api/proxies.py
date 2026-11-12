from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import encrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import PlatformAccount, ProxyEndpoint, User
from backend.app.schemas.common import paginated
from backend.app.services.proxy_service import (
    apply_test_result,
    bulk_create_proxies,
    create_proxy,
    normalize_protocol,
    serialize_proxy,
    test_proxy,
    validate_host,
    validate_port,
)

router = APIRouter(prefix="/proxies", tags=["proxies"])


class ProxyCreateRequest(BaseModel):
    name: str = Field(default="", max_length=128)
    protocol: Literal["http", "https", "socks4", "socks5", "socks5h"] = "http"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(default="", max_length=128)
    password: str = ""
    note: str = ""


class ProxyBulkRequest(BaseModel):
    text: str = Field(min_length=1)
    default_protocol: Literal["http", "https", "socks4", "socks5", "socks5h"] = "http"
    name_prefix: str = Field(default="", max_length=64)
    note: str = ""


class ProxyUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    protocol: Optional[Literal["http", "https", "socks4", "socks5", "socks5h"]] = None
    host: Optional[str] = Field(default=None, max_length=255)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    username: Optional[str] = Field(default=None, max_length=128)
    password: Optional[str] = None
    note: Optional[str] = None
    status: Optional[Literal["unknown", "healthy", "unhealthy", "disabled"]] = None


def _account_counts(db: Session, user_id: int) -> dict[int, int]:
    rows = db.execute(
        select(PlatformAccount.proxy_id, func.count(PlatformAccount.id))
        .where(PlatformAccount.user_id == user_id, PlatformAccount.proxy_id.is_not(None))
        .group_by(PlatformAccount.proxy_id)
    ).all()
    return {int(proxy_id): int(count) for proxy_id, count in rows}


def _get_owned(db: Session, user: User, proxy_id: int) -> ProxyEndpoint:
    proxy = db.get(ProxyEndpoint, proxy_id)
    if proxy is None or proxy.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    return proxy


@router.get("")
def list_proxies(
    proxy_status: Optional[str] = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(ProxyEndpoint).where(ProxyEndpoint.user_id == current_user.id)
    if proxy_status:
        statement = statement.where(ProxyEndpoint.status == proxy_status)
    items = db.scalars(statement.order_by(ProxyEndpoint.id.asc())).all()
    counts = _account_counts(db, current_user.id)
    return paginated(
        [serialize_proxy(item, counts.get(item.id, 0)) for item in items],
        page,
        page_size,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_one_proxy(
    payload: ProxyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        proxy = create_proxy(db, current_user.id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(proxy)
    return serialize_proxy(proxy, 0)


@router.post("/bulk")
def import_proxies(
    payload: ProxyBulkRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lines = payload.text.splitlines()
    result = bulk_create_proxies(
        db,
        current_user.id,
        lines,
        default_protocol=payload.default_protocol,
        name_prefix=payload.name_prefix.strip(),
        note=payload.note,
    )
    db.commit()
    created = result["created"]
    for proxy in created:
        db.refresh(proxy)
    return {
        "created": [serialize_proxy(proxy, 0) for proxy in created],
        "created_count": len(created),
        "errors": result["errors"],
    }


@router.get("/{proxy_id}")
def get_proxy(
    proxy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proxy = _get_owned(db, current_user, proxy_id)
    count = db.scalar(
        select(func.count(PlatformAccount.id)).where(
            PlatformAccount.user_id == current_user.id,
            PlatformAccount.proxy_id == proxy.id,
        )
    )
    return serialize_proxy(proxy, int(count or 0))


@router.patch("/{proxy_id}")
def update_proxy(
    proxy_id: int,
    payload: ProxyUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proxy = _get_owned(db, current_user, proxy_id)
    try:
        if payload.protocol is not None:
            proxy.protocol = normalize_protocol(payload.protocol)
        if payload.host is not None:
            proxy.host = validate_host(payload.host)
        if payload.port is not None:
            proxy.port = validate_port(payload.port)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if payload.name is not None:
        proxy.name = payload.name.strip()[:128]
    if payload.username is not None:
        proxy.username = payload.username.strip()
    if payload.password is not None:
        proxy.password_encrypted = encrypt_text(payload.password) if payload.password else ""
    if payload.note is not None:
        proxy.note = payload.note
    if payload.status is not None:
        proxy.status = payload.status
    proxy.updated_at = shanghai_now()
    db.commit()
    db.refresh(proxy)
    return serialize_proxy(proxy)


@router.delete("/{proxy_id}")
def delete_proxy(
    proxy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proxy = _get_owned(db, current_user, proxy_id)
    for account in db.scalars(
        select(PlatformAccount).where(PlatformAccount.proxy_id == proxy.id)
    ).all():
        account.proxy_id = None
    db.delete(proxy)
    db.commit()
    return {"id": proxy_id, "status": "deleted"}


@router.post("/{proxy_id}/test")
def test_one_proxy(
    proxy_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proxy = _get_owned(db, current_user, proxy_id)
    result = test_proxy(proxy)
    apply_test_result(proxy, result)
    db.commit()
    db.refresh(proxy)
    return {"result": result, "proxy": serialize_proxy(proxy)}


@router.post("/test-all")
def test_all_proxies(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proxies = db.scalars(
        select(ProxyEndpoint)
        .where(
            ProxyEndpoint.user_id == current_user.id,
            ProxyEndpoint.status != "disabled",
        )
        .order_by(ProxyEndpoint.id.asc())
        .limit(limit)
    ).all()
    results = []
    for proxy in proxies:
        result = test_proxy(proxy, timeout=12.0)
        apply_test_result(proxy, result)
        results.append(
            {
                "id": proxy.id,
                "name": proxy.name,
                "ok": result.get("ok"),
                "exit_ip": result.get("exit_ip"),
                "latency_ms": result.get("latency_ms"),
                "message": result.get("message"),
            }
        )
    db.commit()
    return {"total": len(results), "healthy": sum(1 for item in results if item["ok"]), "items": results}


__all__ = ["router"]

from __future__ import annotations

import json
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import BrowserFingerprint, PlatformAccount, User
from backend.app.schemas.common import paginated
from backend.app.services.fingerprint_service import (
    generate_fingerprint,
    serialize_fingerprint,
)

router = APIRouter(prefix="/fingerprints", tags=["fingerprints"])


class FingerprintGenerateRequest(BaseModel):
    target: Literal["pc", "creator"] = "pc"
    count: int = Field(default=1, ge=1, le=50)
    seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)
    name_prefix: str = Field(default="", max_length=64)
    note: str = ""
    validate_profile: bool = True


class FingerprintPreviewRequest(BaseModel):
    target: Literal["pc", "creator"] = "pc"
    seed: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)
    validate_profile: bool = True


class FingerprintUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = None


def _account_counts(db: Session, user_id: int) -> dict[int, int]:
    rows = db.execute(
        select(PlatformAccount.fingerprint_id, func.count(PlatformAccount.id))
        .where(
            PlatformAccount.user_id == user_id,
            PlatformAccount.fingerprint_id.is_not(None),
        )
        .group_by(PlatformAccount.fingerprint_id)
    ).all()
    return {int(fingerprint_id): int(count) for fingerprint_id, count in rows}


@router.get("")
def list_fingerprints(
    target: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(BrowserFingerprint).where(BrowserFingerprint.user_id == current_user.id)
    if target:
        statement = statement.where(BrowserFingerprint.target == target)
    items = db.scalars(statement.order_by(BrowserFingerprint.created_at.desc(), BrowserFingerprint.id.desc())).all()
    counts = _account_counts(db, current_user.id)
    return paginated(
        [serialize_fingerprint(item, counts.get(item.id, 0)) for item in items],
        page,
        page_size,
    )


@router.post("/preview")
def preview_fingerprint(
    payload: FingerprintPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    generated = generate_fingerprint(
        target=payload.target, seed=payload.seed, validate=payload.validate_profile
    )
    return {
        "target": generated.target,
        "seed": generated.seed,
        "summary": generated.summary(),
        "profile": generated.profile,
        "validation": generated.validation,
    }


def _default_name(target: str, index: int, seed: int) -> str:
    label = "Creator" if target == "creator" else "PC"
    return f"{label} 指纹 {index:02d} · {seed % 100000:05d}"


@router.post("", status_code=status.HTTP_201_CREATED)
def create_fingerprints(
    payload: FingerprintGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = shanghai_now()
    created: list[BrowserFingerprint] = []
    for index in range(1, payload.count + 1):
        seed = None
        if payload.seed is not None:
            seed = payload.seed + index - 1
            if seed > 2_147_483_647:
                seed = seed % 2_147_483_647
        generated = generate_fingerprint(
            target=payload.target, seed=seed, validate=payload.validate_profile
        )
        name = f"{payload.name_prefix.strip()}{index}".strip() if payload.name_prefix.strip() else _default_name(payload.target, index, generated.seed)
        fingerprint = BrowserFingerprint(
            user_id=current_user.id,
            name=name[:128],
            target=payload.target,
            seed=generated.seed,
            summary_json=json.dumps(generated.summary(), ensure_ascii=False, separators=(",", ":")),
            profile_json=json.dumps(generated.profile, ensure_ascii=False, separators=(",", ":")),
            note=payload.note,
            created_at=now,
            updated_at=now,
        )
        db.add(fingerprint)
        created.append(fingerprint)
    db.commit()
    for fingerprint in created:
        db.refresh(fingerprint)
    return {
        "created": [serialize_fingerprint(item, 0) for item in created],
        "total": len(created),
    }


def _get_owned(db: Session, user: User, fingerprint_id: int) -> BrowserFingerprint:
    fingerprint = db.get(BrowserFingerprint, fingerprint_id)
    if fingerprint is None or fingerprint.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fingerprint not found")
    return fingerprint


@router.get("/{fingerprint_id}")
def get_fingerprint(
    fingerprint_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fingerprint = _get_owned(db, current_user, fingerprint_id)
    count = db.scalar(
        select(func.count(PlatformAccount.id)).where(
            PlatformAccount.user_id == current_user.id,
            PlatformAccount.fingerprint_id == fingerprint.id,
        )
    )
    return serialize_fingerprint(fingerprint, int(count or 0))


@router.patch("/{fingerprint_id}")
def update_fingerprint(
    fingerprint_id: int,
    payload: FingerprintUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fingerprint = _get_owned(db, current_user, fingerprint_id)
    if payload.name is not None:
        fingerprint.name = payload.name.strip()[:128]
    if payload.note is not None:
        fingerprint.note = payload.note
    fingerprint.updated_at = shanghai_now()
    db.commit()
    db.refresh(fingerprint)
    return serialize_fingerprint(fingerprint)


@router.post("/{fingerprint_id}/regenerate")
def regenerate_fingerprint(
    fingerprint_id: int,
    payload: FingerprintPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fingerprint = _get_owned(db, current_user, fingerprint_id)
    target = payload.target or fingerprint.target
    generated = generate_fingerprint(target=target, seed=payload.seed, validate=payload.validate_profile)
    fingerprint.target = target
    fingerprint.seed = generated.seed
    fingerprint.summary_json = json.dumps(
        generated.summary(), ensure_ascii=False, separators=(",", ":")
    )
    fingerprint.profile_json = json.dumps(
        generated.profile, ensure_ascii=False, separators=(",", ":")
    )
    fingerprint.updated_at = shanghai_now()
    db.commit()
    db.refresh(fingerprint)
    return serialize_fingerprint(fingerprint)


@router.delete("/{fingerprint_id}")
def delete_fingerprint(
    fingerprint_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fingerprint = _get_owned(db, current_user, fingerprint_id)
    for account in db.scalars(
        select(PlatformAccount).where(PlatformAccount.fingerprint_id == fingerprint.id)
    ).all():
        account.fingerprint_id = None
    db.delete(fingerprint)
    db.commit()
    return {"id": fingerprint_id, "status": "deleted"}


@router.post("/{fingerprint_id}/apply")
def apply_to_account(
    fingerprint_id: int,
    account_id: int = Query(..., ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fingerprint = _get_owned(db, current_user, fingerprint_id)
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if fingerprint.target not in {account.sub_type, "any"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"指纹类型 {fingerprint.target} 与账号类型 {account.sub_type} 不匹配",
        )
    account.fingerprint_id = fingerprint.id
    account.updated_at = shanghai_now()
    db.commit()
    return {"fingerprint_id": fingerprint.id, "account_id": account.id}


__all__ = ["router"]

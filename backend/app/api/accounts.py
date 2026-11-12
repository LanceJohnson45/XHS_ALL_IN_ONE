from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AccountCookieVersion,
    BrowserFingerprint,
    PlatformAccount,
    ProxyEndpoint,
    User,
)
from backend.app.schemas.common import paginated
from backend.app.services.account_runtime import load_account_runtime
from backend.app.services.account_service import (
    account_profile_from_user_info,
    cookie_header_from_text,
    decode_cookie_text,
    enrich_user_info_with_xhs_self_profile,
    serialize_account,
    upsert_platform_account_from_login,
)
from xhs_utils.cookie_util import trans_cookies

router = APIRouter(prefix="/accounts", tags=["accounts"])


class CookieImportRequest(BaseModel):
    platform: str = Field(pattern="^xhs$")
    sub_type: str = Field(pattern="^(pc|creator)$")
    cookie_string: str = Field(min_length=3)
    sync_creator: bool = False


class AccountRuntimeUpdate(BaseModel):
    fingerprint_id: Optional[int] = None
    proxy_id: Optional[int] = None


def get_pc_account_adapter() -> XhsPcLoginAdapter:
    return XhsPcLoginAdapter()


def get_creator_account_adapter() -> XhsCreatorLoginAdapter:
    return XhsCreatorLoginAdapter()


class XhsSelfProfileAdapter:
    def __init__(self) -> None:
        self.proxies: Optional[dict] = None
        self.auth_kwargs: dict = {}

    def configure_runtime(self, *, proxies: Optional[dict] = None, auth_kwargs: Optional[dict] = None):
        self.proxies = proxies
        self.auth_kwargs = dict(auth_kwargs or {})
        return self

    def get_self_profile(self, cookies_text: str):
        return XhsPcApiAdapter(
            cookies_text,
            proxies=self.proxies,
            auth_kwargs=self.auth_kwargs,
        ).get_self_info()


def get_xhs_self_profile_adapter() -> XhsSelfProfileAdapter:
    return XhsSelfProfileAdapter()


def _select_adapter(sub_type: str, pc_adapter: XhsPcLoginAdapter, creator_adapter: XhsCreatorLoginAdapter):
    return creator_adapter if sub_type == "creator" else pc_adapter


def _serialize_with_bindings(db: Session, accounts: list[PlatformAccount], action: str | None = None) -> list[dict]:
    fingerprint_ids = {item.fingerprint_id for item in accounts if item.fingerprint_id}
    proxy_ids = {item.proxy_id for item in accounts if item.proxy_id}
    fingerprints = {
        item.id: item for item in db.scalars(select(BrowserFingerprint).where(BrowserFingerprint.id.in_(fingerprint_ids))).all()
    } if fingerprint_ids else {}
    proxies = {
        item.id: item for item in db.scalars(select(ProxyEndpoint).where(ProxyEndpoint.id.in_(proxy_ids))).all()
    } if proxy_ids else {}
    return [
        serialize_account(
            account,
            action,
            fingerprints.get(account.fingerprint_id),
            proxies.get(account.proxy_id),
        )
        for account in accounts
    ]


def _sync_creator_account_from_pc_cookie(
    *,
    db: Session,
    user_id: int,
    platform: str,
    cookie_string: str,
    creator_adapter: XhsCreatorLoginAdapter,
):
    try:
        creator_result = creator_adapter.exchange_from_user_cookies(trans_cookies(cookie_string))
        creator_cookies_text = json.dumps(creator_result["cookies"], ensure_ascii=False, separators=(",", ":"))
        creator_user_info = creator_adapter.get_user_info(creator_result["cookies"])
        upsert_platform_account_from_login(
            db=db,
            user_id=user_id,
            platform=platform,
            sub_type="creator",
            user_info=creator_user_info,
            cookies_text=creator_cookies_text,
        )
    except Exception:
        return None
    return True


@router.get("")
def get_accounts(
    platform: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(PlatformAccount).where(PlatformAccount.user_id == current_user.id)
    if platform:
        statement = statement.where(PlatformAccount.platform == platform)
    accounts = db.scalars(statement.order_by(PlatformAccount.created_at.desc())).all()
    return paginated(
        _serialize_with_bindings(db, list(accounts)),
        page,
        page_size,
    )


@router.post("/import-cookie")
def import_cookie(
    payload: CookieImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_account_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_account_adapter),
    self_profile_adapter: XhsSelfProfileAdapter = Depends(get_xhs_self_profile_adapter),
):
    adapter = _select_adapter(payload.sub_type, pc_adapter, creator_adapter)
    try:
        user_info = adapter.get_user_info(trans_cookies(payload.cookie_string))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cookie is invalid or expired") from exc

    if payload.sub_type == "pc":
        try:
            self_profile = self_profile_adapter.get_self_profile(cookie_header_from_text(payload.cookie_string))
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass

    account, action = upsert_platform_account_from_login(
        db=db,
        user_id=current_user.id,
        platform=payload.platform,
        sub_type=payload.sub_type,
        user_info=user_info,
        cookies_text=payload.cookie_string,
    )
    if payload.sub_type == "pc" and payload.sync_creator:
        _sync_creator_account_from_pc_cookie(
            db=db,
            user_id=current_user.id,
            platform=payload.platform,
            cookie_string=payload.cookie_string,
            creator_adapter=creator_adapter,
        )
    db.commit()
    db.refresh(account)
    return _serialize_with_bindings(db, [account], action)[0]


@router.post("/{account_id}/check")
def check_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_account_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_account_adapter),
    self_profile_adapter: XhsSelfProfileAdapter = Depends(get_xhs_self_profile_adapter),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc())
    ).first()
    if cookie_version is None:
        account.status = "expired"
        account.status_message = "No stored cookie version"
        db.commit()
        db.refresh(account)
        return _serialize_with_bindings(db, [account])[0]

    runtime = load_account_runtime(db, account)
    adapter = runtime.apply_to(_select_adapter(account.sub_type or "pc", pc_adapter, creator_adapter))
    try:
        cookies_text = runtime.cookies or decrypt_text(cookie_version.encrypted_cookies)
        user_info = adapter.get_user_info(decode_cookie_text(cookies_text))
        try:
            if account.sub_type == "creator":
                # The account may carry a Creator fingerprint; its b1/profile shape
                # cannot be fed into the PC signer, so only the proxy applies here.
                self_profile = XhsPcApiAdapter(
                    cookie_header_from_text(cookies_text), proxies=runtime.proxies
                ).get_self_info()
            else:
                profile_adapter = runtime.apply_to(self_profile_adapter)
                self_profile = profile_adapter.get_self_profile(cookie_header_from_text(cookies_text))
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass
        account.status = "active"
        account.status_message = ""
        account.nickname = user_info.get("nickname", account.nickname)
        account.avatar_url = user_info.get("avatar_url", account.avatar_url)
        account.external_user_id = user_info.get("external_user_id", account.external_user_id)
        account.profile_json = json.dumps(account_profile_from_user_info(user_info), ensure_ascii=False, separators=(",", ":"))
        account.updated_at = shanghai_now()

        if account.sub_type == "creator":
            try:
                from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter

                creator_adapter = XhsCreatorApiAdapter(
                    runtime.cookies,
                    proxies=runtime.proxies,
                    auth_kwargs=runtime.auth_kwargs,
                )
                success, msg, _ = creator_adapter.get_file_ids("image")
                if not success:
                    account.status = "expired"
                    account.status_message = f"上传凭证获取失败: {msg}"
            except Exception as upload_exc:
                account.status = "expired"
                account.status_message = f"上传凭证验证异常: {upload_exc}"
    except Exception as exc:
        account.status = "expired"
        account.status_message = str(exc)
        account.updated_at = shanghai_now()

    db.commit()
    db.refresh(account)
    return _serialize_with_bindings(db, [account])[0]


def _resolve_fingerprint(db: Session, user: User, fingerprint_id: int | None, sub_type: str | None) -> BrowserFingerprint | None:
    if fingerprint_id is None:
        return None
    fingerprint = db.get(BrowserFingerprint, fingerprint_id)
    if fingerprint is None or fingerprint.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fingerprint not found")
    if fingerprint.target not in {sub_type, "any"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"指纹类型 {fingerprint.target} 与账号类型 {sub_type} 不匹配",
        )
    return fingerprint


def _resolve_proxy(db: Session, user: User, proxy_id: int | None) -> ProxyEndpoint | None:
    if proxy_id is None:
        return None
    proxy = db.get(ProxyEndpoint, proxy_id)
    if proxy is None or proxy.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    return proxy


@router.patch("/{account_id}")
def update_account(
    account_id: int,
    payload: AccountRuntimeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    changed_fields = payload.model_fields_set
    if "fingerprint_id" in changed_fields:
        _resolve_fingerprint(db, current_user, payload.fingerprint_id, account.sub_type)
        account.fingerprint_id = payload.fingerprint_id
    if "proxy_id" in changed_fields:
        _resolve_proxy(db, current_user, payload.proxy_id)
        account.proxy_id = payload.proxy_id
    account.updated_at = shanghai_now()
    db.commit()
    db.refresh(account)
    return _serialize_with_bindings(db, [account])[0]


@router.get("/{account_id}/runtime")
def get_account_runtime(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    runtime = load_account_runtime(db, account)
    return {
        "account_id": account.id,
        "sub_type": account.sub_type,
        "fingerprint_id": runtime.fingerprint_id,
        "proxy_id": runtime.proxy_id,
        "proxy_configured": runtime.proxies is not None,
        "proxy_url_masked": (
            (runtime.proxies or {}).get("https", "").split("@")[-1]
            if runtime.proxies
            else None
        ),
        "fingerprint_applied": bool(runtime.auth_kwargs),
        "warnings": runtime.warnings,
    }


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.get(PlatformAccount, account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    for cookie_version in db.scalars(
        select(AccountCookieVersion).where(AccountCookieVersion.platform_account_id == account.id)
    ).all():
        db.delete(cookie_version)
    db.delete(account)
    db.commit()
    return {"id": account_id, "status": "deleted"}

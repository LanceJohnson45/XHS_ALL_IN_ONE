"""Resolve the effective runtime identity (cookies + proxy + fingerprint) for
one platform account.

Every adapter call site should go through :func:`load_account_runtime` so that
an account's assigned proxy and fingerprint are actually used by the signer.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text
from backend.app.models import AccountCookieVersion, BrowserFingerprint, PlatformAccount, ProxyEndpoint
from backend.app.services.proxy_service import proxies_dict_for
from xhs_utils.xhs_pc.state import REFERENCE_PROFILE as PC_REFERENCE, parse_cookie_kv as parse_pc_cookies
from xhs_utils.xhs_creator.state import REFERENCE_PROFILE as CREATOR_REFERENCE
from xhs_utils.xhs_creator.state import parse_cookie_kv as parse_creator_cookies


@dataclass
class AccountRuntime:
    cookies: str = ""
    proxies: Optional[dict[str, str]] = None
    auth_kwargs: dict[str, Any] = field(default_factory=dict)
    fingerprint_id: Optional[int] = None
    proxy_id: Optional[int] = None
    warnings: list[str] = field(default_factory=list)

    def apply_to(self, adapter: Any) -> Any:
        if hasattr(adapter, "configure_runtime"):
            adapter.configure_runtime(proxies=self.proxies, auth_kwargs=self.auth_kwargs)
        return adapter


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_cookies_text(value: str) -> str:
    """Accept either a Cookie header or the stored JSON map and return a header."""
    stripped = str(value or "").strip()
    if not stripped.startswith("{"):
        return stripped
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if not isinstance(parsed, dict):
        return stripped
    return "; ".join(f"{key}={item}" for key, item in parsed.items())


def latest_cookies_text(db: Session, account: PlatformAccount) -> str:
    version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc(), AccountCookieVersion.id.desc())
    ).first()
    if version is None:
        return ""
    return normalize_cookies_text(decrypt_text(version.encrypted_cookies))


def _decode_started_at(cookies: str, target: str) -> int:
    import time

    parser = parse_creator_cookies if target == "creator" else parse_pc_cookies
    try:
        values = parser(cookies)
        loadts = int(values.get("loadts") or 0)
    except Exception:
        loadts = 0
    return loadts if loadts > 0 else int(time.time() * 1000)


def _merged_release(target: str, profile: dict[str, Any]) -> dict[str, Any]:
    reference = CREATOR_REFERENCE if target == "creator" else PC_REFERENCE
    release = dict(reference.get("release") or {})
    override = profile.get("release")
    if isinstance(override, dict):
        release.update({str(k): v for k, v in override.items() if v is not None})
    return release


def _pc_b1_state(profile: dict[str, Any], started_at: int) -> Any:
    from xhs_utils.xhs_pc.state import B1RuntimeState

    b1 = dict(profile.get("b1") or {})
    state = B1RuntimeState.reference(started_at=started_at)
    state.frame_count = int(b1.get("frame_count", state.frame_count))
    state.x39_value = int(b1.get("x39_value", state.x39_value))
    state.x50_value = str(b1.get("x50_value", state.x50_value))
    state.sec_canvas = str(b1.get("sec_canvas", state.sec_canvas))
    state.selected_global_names = [
        str(item) for item in b1.get("selected_global_names", state.selected_global_names)
    ]
    if b1.get("time_origin_offset_ms") is not None:
        state.time_origin_ms = float(started_at) + float(b1["time_origin_offset_ms"])
    if b1.get("generated_at_offset_ms") is not None:
        state.generated_at_offset_ms = int(b1["generated_at_offset_ms"])
    state.telemetry_profile = str(b1.get("telemetry_profile", state.telemetry_profile))
    state.telemetry_template = str(b1.get("telemetry_template", state.telemetry_template))
    state.mouse = dict(b1.get("mouse") or {})
    state.keyboard = dict(b1.get("keyboard") or {})
    state.page = dict(b1.get("page") or {})
    state.state = dict(b1.get("state") or {})
    state.features = dict(b1.get("features") or {})
    state.overrides.update(dict(b1.get("overrides") or {}))
    return state


def _creator_b1_state(profile: dict[str, Any], started_at: int) -> Any:
    from xhs_utils.xhs_creator.state import CreatorB1RuntimeState

    b1 = dict(profile.get("b1") or {})
    state = CreatorB1RuntimeState.reference(started_at=started_at)
    state.frame_count = int(b1.get("frame_count", state.frame_count))
    state.x39_value = int(b1.get("x39_value", state.x39_value))
    state.x50_value = str(b1.get("x50_value", state.x50_value))
    state.x51_value = str(b1.get("x51_value", state.x51_value))
    state.x37_value = str(b1.get("x37_value", state.x37_value))
    state.x38_value = str(b1.get("x38_value", state.x38_value))
    state.sec_canvas = str(b1.get("sec_canvas", state.sec_canvas))
    state.selected_global_names = [
        str(item) for item in b1.get("selected_global_names", state.selected_global_names)
    ]
    if b1.get("time_origin_offset_ms") is not None:
        state.time_origin_ms = float(started_at) + float(b1["time_origin_offset_ms"])
    if b1.get("generated_at_offset_ms") is not None:
        state.generated_at_offset_ms = int(b1["generated_at_offset_ms"])
    state.mouse = dict(b1.get("mouse") or {})
    state.keyboard = dict(b1.get("keyboard") or {})
    state.page = dict(b1.get("page") or {})
    state.state = dict(b1.get("state") or {})
    state.features = dict(b1.get("features") or {})
    return state


def fingerprint_auth_kwargs(
    fingerprint: BrowserFingerprint,
    *,
    target: str,
    cookies: str = "",
) -> dict[str, Any]:
    profile = _json_object(fingerprint.profile_json)
    if not profile:
        return {}
    started_at = _decode_started_at(cookies, target)
    kwargs: dict[str, Any] = {
        "release": _merged_release(target, profile),
        "web_profile_fields": dict(profile.get("web_profile_fields") or {}),
    }
    if target == "creator":
        kwargs["b1_state"] = _creator_b1_state(profile, started_at)
        return kwargs
    kwargs["b1_state"] = _pc_b1_state(profile, started_at)
    if profile.get("web_profile_i12_seed") is not None:
        kwargs["web_profile_i12_seed"] = int(profile["web_profile_i12_seed"])
    if profile.get("web_profile_fi") is not None:
        kwargs["web_profile_fi"] = int(profile["web_profile_fi"])
    if profile.get("rap_fingerprint_hex"):
        kwargs["rap_fingerprint_hex"] = str(profile["rap_fingerprint_hex"])
    if profile.get("mns_env"):
        kwargs["mns_env"] = dict(profile["mns_env"])
    return kwargs


def load_account_runtime(
    db: Session,
    account: PlatformAccount,
    *,
    cookies: str | None = None,
    include_fingerprint: bool = True,
) -> AccountRuntime:
    target = account.sub_type or "pc"
    runtime = AccountRuntime(
        cookies=(
            latest_cookies_text(db, account)
            if cookies is None
            else normalize_cookies_text(cookies)
        ),
        fingerprint_id=account.fingerprint_id,
        proxy_id=account.proxy_id,
    )

    if account.proxy_id:
        proxy = db.get(ProxyEndpoint, account.proxy_id)
        if proxy is None or proxy.user_id != account.user_id:
            runtime.warnings.append("绑定的代理不存在，已回退为直连")
            runtime.proxy_id = None
        elif proxy.status == "disabled":
            runtime.warnings.append("绑定的代理已停用，已回退为直连")
        else:
            runtime.proxies = proxies_dict_for(proxy)

    if include_fingerprint and account.fingerprint_id:
        fingerprint = db.get(BrowserFingerprint, account.fingerprint_id)
        if fingerprint is None or fingerprint.user_id != account.user_id:
            runtime.warnings.append("绑定的指纹不存在，已回退为默认指纹")
            runtime.fingerprint_id = None
        elif fingerprint.target not in {target, "any"}:
            runtime.warnings.append(
                f"指纹类型 {fingerprint.target} 与账号类型 {target} 不匹配，已忽略"
            )
            runtime.fingerprint_id = None
        else:
            runtime.auth_kwargs = fingerprint_auth_kwargs(
                fingerprint, target=target, cookies=runtime.cookies
            )
    return runtime


def supports_runtime_kwargs(factory: Callable[..., Any]) -> bool:
    try:
        parameters = inspect.signature(factory).parameters
    except (TypeError, ValueError):
        return False
    return "proxies" in parameters and "auth_kwargs" in parameters


def build_adapter(factory: Callable[..., Any], runtime: AccountRuntime) -> Any:
    """Instantiate an adapter with runtime identity, tolerating 1-arg factories."""
    if supports_runtime_kwargs(factory):
        return factory(runtime.cookies, proxies=runtime.proxies, auth_kwargs=runtime.auth_kwargs)
    return factory(runtime.cookies)


__all__ = [
    "AccountRuntime",
    "build_adapter",
    "fingerprint_auth_kwargs",
    "latest_cookies_text",
    "load_account_runtime",
    "normalize_cookies_text",
    "supports_runtime_kwargs",
]

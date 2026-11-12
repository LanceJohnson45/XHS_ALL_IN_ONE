"""Proxy endpoints: parsing, persistence helpers and connectivity probing.

A "proxy" here is one purchased static line (host + port + optional auth). The
user can import them in bulk and bind one line to each account.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable, Optional
from urllib.parse import quote, unquote, urlsplit

from sqlalchemy.orm import Session

from backend.app.core.security import decrypt_text, encrypt_text
from backend.app.core.time import shanghai_now

SUPPORTED_PROTOCOLS = ("http", "https", "socks4", "socks5", "socks5h")
STATUS_VALUES = ("unknown", "healthy", "unhealthy", "disabled")

_TEST_ENDPOINT = (
    "http://ip-api.com/json/?fields=status,message,country,regionName,city,lat,lon,query&lang=zh-CN"
)
_TEST_FALLBACK_ENDPOINT = "https://api.ipify.org?format=json"

_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-\.]{0,253}[A-Za-z0-9])?$")


def normalize_protocol(value: str | None) -> str:
    protocol = str(value or "http").strip().lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"不支持的代理协议: {protocol}")
    return protocol


def validate_host(value: str) -> str:
    host = str(value or "").strip()
    if not host or not _HOSTNAME_RE.match(host):
        raise ValueError(f"无效的代理主机: {value!r}")
    return host


def validate_port(value: Any) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"无效的代理端口: {value!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"代理端口超出范围: {port}")
    return port


def parse_proxy_line(line: str, *, default_protocol: str = "http") -> dict[str, Any]:
    """Parse one pasted proxy line into structured fields.

    Accepted shapes::

        http://user:pass@1.2.3.4:8080
        socks5://user:pass@proxy.example.com:1080
        1.2.3.4:8080
        1.2.3.4:8080:user:pass
        user:pass@1.2.3.4:8080
    """
    raw = str(line or "").strip()
    if not raw or raw.startswith("#"):
        raise ValueError("空行")

    protocol = normalize_protocol(default_protocol)
    username = ""
    password = ""
    host = ""
    port = ""

    if "://" in raw:
        parsed = urlsplit(raw)
        protocol = normalize_protocol(parsed.scheme or default_protocol)
        username = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
        host = parsed.hostname or ""
        port = str(parsed.port or "")
    elif "@" in raw:
        credentials, address = raw.rsplit("@", 1)
        if ":" in credentials:
            username, password = credentials.split(":", 1)
        else:
            username = credentials
        host, _, port = address.rpartition(":")
    else:
        parts = raw.split(":")
        if len(parts) == 2:
            host, port = parts
        elif len(parts) == 4:
            host, port, username, password = parts
        else:
            raise ValueError(f"无法识别的代理格式: {raw}")

    host = validate_host(host)
    port_value = validate_port(port)
    return {
        "protocol": protocol,
        "host": host,
        "port": port_value,
        "username": username.strip(),
        "password": password,
    }


def proxy_signature(protocol: str, host: str, port: int, username: str = "") -> tuple:
    return (protocol or "http", (host or "").lower(), int(port or 0), username or "")


def build_proxy_url(proxy: Any, *, mask_password: bool = False) -> str:
    protocol = normalize_protocol(getattr(proxy, "protocol", "http"))
    host = getattr(proxy, "host", "")
    port = int(getattr(proxy, "port", 0) or 0)
    username = getattr(proxy, "username", "") or ""
    password = ""
    encrypted = getattr(proxy, "password_encrypted", "") or ""
    if encrypted:
        try:
            password = decrypt_text(encrypted)
        except Exception:
            password = ""
    credentials = ""
    if username:
        credentials = quote(username, safe="")
        if password:
            credentials += ":" + ("" if mask_password else quote(password, safe=""))
        credentials += "@"
    elif password:
        credentials = ":" + ("" if mask_password else quote(password, safe="")) + "@"
    return f"{protocol}://{credentials}{host}:{port}"


def proxies_dict_for(proxy: Any) -> dict[str, str]:
    url = build_proxy_url(proxy)
    return {"http": url, "https": url}


def serialize_proxy(proxy: Any, account_count: int = 0) -> dict[str, Any]:
    return {
        "id": proxy.id,
        "name": proxy.name,
        "protocol": proxy.protocol,
        "host": proxy.host,
        "port": proxy.port,
        "address": f"{proxy.host}:{proxy.port}",
        "url_masked": build_proxy_url(proxy, mask_password=True),
        "username": proxy.username,
        "has_password": bool(proxy.password_encrypted),
        "status": proxy.status,
        "status_message": proxy.status_message,
        "exit_ip": proxy.exit_ip,
        "exit_country": proxy.exit_country,
        "exit_region": proxy.exit_region,
        "latitude": proxy.latitude,
        "longitude": proxy.longitude,
        "latency_ms": proxy.latency_ms,
        "note": proxy.note,
        "account_count": account_count,
        "last_checked_at": proxy.last_checked_at.isoformat() if proxy.last_checked_at else None,
        "created_at": proxy.created_at.isoformat() if proxy.created_at else None,
        "updated_at": (proxy.updated_at or proxy.created_at).isoformat()
        if (proxy.updated_at or proxy.created_at)
        else None,
    }


def create_proxy(db: Session, user_id: int, payload: dict[str, Any]) -> Any:
    from backend.app.models import ProxyEndpoint

    protocol = normalize_protocol(payload.get("protocol"))
    host = validate_host(payload.get("host", ""))
    port = validate_port(payload.get("port"))
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    proxy = ProxyEndpoint(
        user_id=user_id,
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password_encrypted=encrypt_text(password) if password else "",
        name=str(payload.get("name") or "").strip() or f"{host}:{port}",
        note=str(payload.get("note") or ""),
        status="unknown",
    )
    db.add(proxy)
    db.flush()
    return proxy


def bulk_create_proxies(
    db: Session,
    user_id: int,
    lines: Iterable[str],
    *,
    default_protocol: str = "http",
    name_prefix: str = "",
    note: str = "",
) -> dict[str, Any]:
    from backend.app.models import ProxyEndpoint

    existing = db.query(ProxyEndpoint).filter(ProxyEndpoint.user_id == user_id).all()
    seen = {
        proxy_signature(item.protocol, item.host, item.port, item.username)
        for item in existing
    }
    created: list[Any] = []
    errors: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if not str(line).strip() or str(line).strip().startswith("#"):
            continue
        try:
            parsed = parse_proxy_line(line, default_protocol=default_protocol)
        except ValueError as exc:
            errors.append({"line": index, "value": str(line)[:200], "error": str(exc)})
            continue
        signature = proxy_signature(
            parsed["protocol"], parsed["host"], parsed["port"], parsed["username"]
        )
        if signature in seen:
            errors.append(
                {"line": index, "value": str(line)[:200], "error": "重复的代理（已跳过）"}
            )
            continue
        seen.add(signature)
        name = f"{name_prefix}{index}" if name_prefix else f"{parsed['host']}:{parsed['port']}"
        proxy = ProxyEndpoint(
            user_id=user_id,
            protocol=parsed["protocol"],
            host=parsed["host"],
            port=parsed["port"],
            username=parsed["username"],
            password_encrypted=encrypt_text(parsed["password"]) if parsed["password"] else "",
            name=name,
            note=note,
            status="unknown",
        )
        db.add(proxy)
        created.append(proxy)
    db.flush()
    return {"created": created, "errors": errors}


def test_proxy(proxy: Any, timeout: float = 15.0) -> dict[str, Any]:
    """Probe the exit IP through the proxy. Network failures are non-fatal."""
    from curl_cffi import requests as curl_requests

    proxies = proxies_dict_for(proxy)
    started = time.perf_counter()
    result: dict[str, Any] = {
        "ok": False,
        "exit_ip": "",
        "country": "",
        "region": "",
        "city": "",
        "latitude": None,
        "longitude": None,
        "latency_ms": None,
        "message": "",
    }
    try:
        response = curl_requests.get(
            _TEST_ENDPOINT,
            proxies=proxies,
            timeout=timeout,
            impersonate="chrome",
        )
        latency = int((time.perf_counter() - started) * 1000)
        result["latency_ms"] = latency
        payload = response.json()
        if payload.get("status") == "success" and payload.get("query"):
            result.update(
                {
                    "ok": True,
                    "exit_ip": str(payload.get("query") or ""),
                    "country": str(payload.get("country") or ""),
                    "region": str(payload.get("regionName") or ""),
                    "city": str(payload.get("city") or ""),
                    "latitude": payload.get("lat"),
                    "longitude": payload.get("lon"),
                    "message": "ok",
                }
            )
            return result
        result["message"] = str(payload.get("message") or "代理探测失败")
    except Exception as exc:  # pragma: no cover - network dependent
        result["message"] = str(exc)[:300]

    try:
        started = time.perf_counter()
        response = curl_requests.get(
            _TEST_FALLBACK_ENDPOINT,
            proxies=proxies,
            timeout=timeout,
            impersonate="chrome",
        )
        latency = int((time.perf_counter() - started) * 1000)
        payload = response.json()
        exit_ip = str(payload.get("ip") or "")
        if exit_ip:
            result.update(
                {
                    "ok": True,
                    "exit_ip": exit_ip,
                    "latency_ms": latency,
                    "message": "ok（仅获取到出口 IP）",
                }
            )
    except Exception as exc:  # pragma: no cover
        if not result["message"]:
            result["message"] = str(exc)[:300]
    return result


def apply_test_result(proxy: Any, result: dict) -> None:
    now = shanghai_now()
    proxy.last_checked_at = now
    if result.get("ok"):
        proxy.status = "healthy"
        proxy.status_message = ""
        proxy.exit_ip = str(result.get("exit_ip") or "")
        proxy.exit_country = str(result.get("country") or "")
        proxy.exit_region = str(result.get("region") or "")
        proxy.latitude = result.get("latitude")
        proxy.longitude = result.get("longitude")
        proxy.latency_ms = result.get("latency_ms")
    else:
        proxy.status = "unhealthy"
        proxy.status_message = str(result.get("message") or "代理不可用")[:500]
        proxy.latency_ms = result.get("latency_ms")
    proxy.updated_at = now


__all__ = [
    "SUPPORTED_PROTOCOLS",
    "STATUS_VALUES",
    "apply_test_result",
    "build_proxy_url",
    "bulk_create_proxies",
    "create_proxy",
    "normalize_protocol",
    "parse_proxy_line",
    "proxies_dict_for",
    "proxy_signature",
    "serialize_proxy",
    "test_proxy",
    "validate_host",
    "validate_port",
]

"""Deterministic fingerprint generation for XHS PC / Creator accounts.

The generated profile is *data only*. It is injected into the existing signer
through the same public seams the SDK already exposes
(``web_profile_fields``, ``b1_state``, ``release``, ``web_profile_i12_seed`` and
``web_profile_fi``), so no signing logic is reimplemented here.

Design rule: only fields whose semantics and self-consistency we can verify are
randomized. OS / GPU / font / canvas-hash values stay on the checked-in
reference device because inventing an unverified combination is more of a
detection signal than a protection. Variation comes from display geometry,
timezone/locale, hardware capacity, Chrome build, b1 interaction counters and
the webprofile timing seeds.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from xhs_utils.xhs_pc.state import REFERENCE_PROFILE as PC_REFERENCE
from xhs_utils.xhs_creator.state import REFERENCE_PROFILE as CREATOR_REFERENCE

SCHEMA_VERSION = 1

SUPPORTED_TARGETS = ("pc", "creator")

_CHROME_BUILDS = (
    "150.0.0.0",
    "150.0.7339.41",
    "150.0.7339.80",
    "150.0.7339.127",
)

_SCREENS = (
    (1920, 1080, 1.0),
    (1920, 1080, 1.25),
    (2560, 1440, 1.0),
    (2560, 1440, 1.25),
    (2880, 1800, 1.5),
    (3840, 2160, 1.5),
)

_TIMEZONE_LOCALES = (
    ("Asia/Shanghai", "zh-CN", ("zh-CN", "zh")),
    ("Asia/Hong_Kong", "zh-HK", ("zh-HK", "zh", "en")),
    ("Asia/Taipei", "zh-TW", ("zh-TW", "zh", "en")),
    ("Asia/Singapore", "en-SG", ("en-SG", "en", "zh-CN")),
    ("Asia/Tokyo", "ja-JP", ("ja-JP", "ja", "en-US")),
    ("America/Los_Angeles", "en-US", ("en-US", "en")),
    ("Europe/London", "en-GB", ("en-GB", "en")),
)

_HARDWARE_CONCURRENCY = (8, 12, 16, 20, 24)
_DEVICE_MEMORY = (8, 16, 32)

_PC_WEBGL = (
    PC_REFERENCE["webProfile"]["fields"]["x7"],
    PC_REFERENCE["webProfile"]["fields"]["x56"],
)


@dataclass(frozen=True)
class GeneratedFingerprint:
    target: str
    seed: int
    profile: dict[str, Any]
    validation: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        return build_summary(self.profile)


def _rng(seed: int, target: str) -> random.Random:
    # xor the textual target so a PC and a Creator fingerprint can share a seed
    # without producing the same telemetry.
    digest = hashlib.sha256(f"{target}:{seed}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _reference(target: str) -> Mapping[str, Any]:
    return CREATOR_REFERENCE if target == "creator" else PC_REFERENCE


def _chrome_sec_ch_ua(build: str) -> str:
    major = build.split(".", 1)[0]
    return f'"Not;A=Brand";v="8", "Chromium";v="{major}", "Google Chrome";v="{major}"'


def _windows_user_agent(build: str) -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{build} Safari/537.36"
    )


def _pick_telemetry(rng: random.Random) -> dict[str, Any]:
    mouse_click = rng.randint(1, 8)
    return {
        "mouse": {
            "me": rng.randint(18, 120),
            "mm": rng.randint(40, 260),
            "md": mouse_click,
            "mu": mouse_click,
            "c": mouse_click,
            "dc": rng.randint(0, 3),
        },
        "page": {
            "ulr": rng.randint(1, 12),
            "ps": rng.randint(1, 4),
            "f": rng.randint(4, 40),
            "b": rng.randint(1, 30),
            "vc": rng.randint(0, 6),
            "rs": 1,
            "sc": 1,
        },
        "state": {"h": 0, "f": 1, "kr": 0},
        "features": {
            "ae": round(rng.uniform(2.0, 5.5), 15),
            "ak": round(rng.uniform(3.5, 8.5), 15),
            "cdr": round(rng.uniform(0.02, 0.4), 15),
            "bf": {
                "ar": round(rng.uniform(0.2, 1.0), 15),
                "fr": round(rng.uniform(2.0, 9.0), 15),
            },
            "fi": rng.randint(900, 9000),
        },
    }


def _subset_names(rng: random.Random, names: list[str], minimum: int = 6) -> list[str]:
    if len(names) <= minimum:
        return list(names)
    keep = rng.randint(minimum, len(names))
    indexes = sorted(rng.sample(range(len(names)), keep))
    return [names[index] for index in indexes]


def _generate_pc(rng: random.Random, seed: int) -> dict[str, Any]:
    release = dict(PC_REFERENCE["release"])
    b1_reference = dict(PC_REFERENCE["b1Reference"])

    build = rng.choice(_CHROME_BUILDS)
    user_agent = _windows_user_agent(build)
    sec_ch_ua = _chrome_sec_ch_ua(build)

    screen_width, screen_height, scale = rng.choice(_SCREENS)
    taskbar = rng.choice((40, 48))
    avail_height = max(600, screen_height - taskbar)
    tz_name, locale, languages = rng.choice(_TIMEZONE_LOCALES)
    hardware = rng.choice(_HARDWARE_CONCURRENCY)
    memory = rng.choice(_DEVICE_MEMORY)

    overrides: dict[str, Any] = {
        "x1": user_agent,
        "x3": locale,
        "x8": str(hardware),
        "x9": f"{screen_width};{screen_height}",
        "x10": f"{screen_width};{avail_height}",
        "x12": tz_name,
        "x19": "Win32",
    }

    generated_release = {
        **release,
        "userAgent": user_agent,
        "secChUa": sec_ch_ua,
        "platform": "Windows",
    }

    telemetry = _pick_telemetry(rng)
    selected_names = _subset_names(rng, list(b1_reference.get("selectedGlobalNames") or []))
    b1 = {
        "frame_count": rng.randint(1, 6),
        "x39_value": rng.randint(0, 60),
        "x50_value": ",".join(str(rng.randint(70, 150)) for _ in range(3)),
        "sec_canvas": b1_reference.get("secCanvas", "__SEC_CAV__1-1-1-1-1|"),
        "generated_at_offset_ms": rng.randint(-9000, 4000),
        "selected_global_names": selected_names,
        "time_origin_offset_ms": round(rng.uniform(-5000.0, -400.0), 1),
        "telemetry_profile": b1_reference.get("telemetryProfile", "active"),
        "telemetry_template": b1_reference.get("telemetryTemplate", ""),
        "mouse": telemetry["mouse"],
        "keyboard": {},
        "page": telemetry["page"],
        "state": telemetry["state"],
        "features": telemetry["features"],
        "overrides": {
            "x37": b1_reference.get("x37", ""),
            "x38": b1_reference.get("x38", ""),
        },
    }

    profile = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "xhs-browser-fingerprint",
        "target": "pc",
        "seed": seed,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "os": {
            "name": "windows",
            "platform": "Win32",
            "clientHintPlatform": "Windows",
        },
        "browser": {
            "name": "Google Chrome",
            "major": int(build.split(".", 1)[0]),
            "fullVersion": build,
            "userAgent": user_agent,
            "secChUa": sec_ch_ua,
        },
        "display": {
            "screenWidth": screen_width,
            "screenHeight": screen_height,
            "availWidth": screen_width,
            "availHeight": avail_height,
            "deviceScaleFactor": scale,
            "colorDepth": 24,
            "pixelDepth": 24,
        },
        "navigator": {
            "timezone": tz_name,
            "locale": locale,
            "languages": list(languages),
            "hardwareConcurrency": hardware,
            "deviceMemory": memory,
            "platform": "Win32",
        },
        "graphics": {
            "vendor": _PC_WEBGL[0].split(",", 1)[0],
            "renderer": _PC_WEBGL[0].split(",", 1)[1] if "," in _PC_WEBGL[0] else _PC_WEBGL[0],
            "x56": _PC_WEBGL[1],
        },
        "release": generated_release,
        "web_profile_fields": overrides,
        "web_profile_i12_seed": rng.randint(0, 255),
        "web_profile_fi": rng.randint(0, 1_000_000),
        "b1": b1,
        "mns_env": {},
        "rap_fingerprint_hex": "",
    }
    return profile


def _generate_creator(rng: random.Random, seed: int) -> dict[str, Any]:
    release = dict(CREATOR_REFERENCE["release"])
    web_fields = dict(CREATOR_REFERENCE["webProfile"]["fields"])
    b1_reference = dict(CREATOR_REFERENCE["b1Reference"])

    build = rng.choice(_CHROME_BUILDS)
    user_agent = _windows_user_agent(build)
    sec_ch_ua = _chrome_sec_ch_ua(build)

    screen_width, screen_height, scale = rng.choice(_SCREENS)
    taskbar = rng.choice((40, 48))
    avail_height = max(600, screen_height - taskbar)
    tz_name, locale, languages = rng.choice(_TIMEZONE_LOCALES)
    hardware = rng.choice(_HARDWARE_CONCURRENCY)
    memory = rng.choice(_DEVICE_MEMORY)

    overrides: dict[str, Any] = {
        "x1": user_agent,
        "x3": locale,
        "x8": str(hardware),
        "x9": f"{screen_width};{screen_height}",
        "x10": f"{screen_width};{avail_height}",
        "x12": tz_name,
        "x19": "Win32",
    }

    generated_release = {
        **release,
        "userAgent": user_agent,
        "secChUa": sec_ch_ua,
        "platform": "Windows",
    }

    telemetry = _pick_telemetry(rng)
    selected_names = _subset_names(
        rng, list(b1_reference.get("selectedGlobalNames") or []), minimum=8
    )
    b1 = {
        "frame_count": rng.randint(1, 8),
        "x39_value": rng.randint(0, 60),
        "x50_value": str(b1_reference.get("x50") or ""),
        "x51_value": str(b1_reference.get("x51") or ""),
        "generated_at_offset_ms": rng.randint(-9000, 4000),
        "sec_canvas": b1_reference.get("secCanvas", "__SEC_CAV__1-1-1-1-1|__SEC_UD__|"),
        "x37_value": b1_reference.get("x37", ""),
        "x38_value": b1_reference.get("x38", ""),
        "selected_global_names": selected_names,
        "time_origin_offset_ms": round(rng.uniform(-5000.0, -400.0), 1),
        "mouse": telemetry["mouse"],
        "keyboard": {},
        "page": telemetry["page"],
        "state": telemetry["state"],
        "features": telemetry["features"],
        "overrides": {},
    }

    profile = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "xhs-browser-fingerprint",
        "target": "creator",
        "seed": seed,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "os": {
            "name": "windows",
            "platform": "Win32",
            "clientHintPlatform": "Windows",
        },
        "browser": {
            "name": "Google Chrome",
            "major": int(build.split(".", 1)[0]),
            "fullVersion": build,
            "userAgent": user_agent,
            "secChUa": sec_ch_ua,
        },
        "display": {
            "screenWidth": screen_width,
            "screenHeight": screen_height,
            "availWidth": screen_width,
            "availHeight": avail_height,
            "deviceScaleFactor": scale,
            "colorDepth": 24,
            "pixelDepth": 24,
        },
        "navigator": {
            "timezone": tz_name,
            "locale": locale,
            "languages": list(languages),
            "hardwareConcurrency": hardware,
            "deviceMemory": memory,
            "platform": "Win32",
        },
        "graphics": {
            "vendor": web_fields.get("x75", ""),
            "renderer": web_fields.get("x7", "").split(",", 1)[-1],
            "x56": web_fields.get("x56", ""),
        },
        "release": generated_release,
        "web_profile_fields": overrides,
        "web_profile_i12_seed": None,
        "web_profile_fi": None,
        "b1": b1,
        "mns_env": {},
        "rap_fingerprint_hex": "",
    }
    return profile


def _finalize_validation(result: dict[str, Any]) -> dict[str, Any]:
    messages = " ".join(str(item) for item in result.get("errors") or [])
    if "Cannot find module" in messages or "cannot find module" in messages:
        result["unavailable"] = True
    return result


def validate_profile(target: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    """Best-effort runtime validation through the bundled signer algorithms."""
    result: dict[str, Any] = {"profileData": False, "b1": False, "errors": []}

    if target == "creator":
        from xhs_utils.xhs_creator.runtime import generate_profile_data
        from xhs_utils.xhs_creator.state import CreatorB1RuntimeState
        from xhs_utils.xhs_creator import runtime as creator_runtime

        b1 = dict(profile.get("b1") or {})
        started = int(time.time() * 1000)
        state = CreatorB1RuntimeState.reference(started_at=started)
        state.frame_count = int(b1.get("frame_count", state.frame_count))
        state.x39_value = int(b1.get("x39_value", state.x39_value))
        state.x50_value = str(b1.get("x50_value", state.x50_value))
        state.x51_value = str(b1.get("x51_value", state.x51_value))
        state.x37_value = str(b1.get("x37_value", state.x37_value))
        state.x38_value = str(b1.get("x38_value", state.x38_value))
        state.selected_global_names = list(
            b1.get("selected_global_names", state.selected_global_names)
        )
        if b1.get("time_origin_offset_ms") is not None:
            state.time_origin_ms = started + float(b1["time_origin_offset_ms"])
        if b1.get("generated_at_offset_ms") is not None:
            state.generated_at_offset_ms = int(b1["generated_at_offset_ms"])
        state.mouse = dict(b1.get("mouse") or {})
        state.keyboard = dict(b1.get("keyboard") or {})
        state.page = dict(b1.get("page") or {})
        state.state = dict(b1.get("state") or {})
        state.features = dict(b1.get("features") or {})
        try:
            creator_runtime.generate_b1(state.to_b1_options(started))
            result["b1"] = True
        except Exception as exc:  # pragma: no cover - depends on Node runtime
            result["errors"].append(f"b1: {exc}")

        try:
            generate_profile_data(
                {
                    "timestampMs": started,
                    "timeOrigin": float(state.time_origin_ms),
                    "documentCookie": "ets=1; a1=00000000000000000000000000000000",
                    "location": "https://creator.xiaohongshu.com/login",
                    "referer": "https://creator.xiaohongshu.com/login",
                    "fields": dict(profile.get("web_profile_fields") or {}),
                }
            )
            result["profileData"] = True
        except Exception as exc:  # pragma: no cover
            result["errors"].append(f"profileData: {exc}")
        return _finalize_validation(result)

    from xhs_utils.xhs_pc.runtime import generate_b1, generate_profile_data
    from xhs_utils.xhs_pc.state import B1RuntimeState

    b1 = dict(profile.get("b1") or {})
    started = int(time.time() * 1000)
    state = B1RuntimeState.reference(started_at=started)
    state.frame_count = int(b1.get("frame_count", state.frame_count))
    state.x39_value = int(b1.get("x39_value", state.x39_value))
    state.x50_value = str(b1.get("x50_value", state.x50_value))
    state.sec_canvas = str(b1.get("sec_canvas", state.sec_canvas))
    state.selected_global_names = list(
        b1.get("selected_global_names", state.selected_global_names)
    )
    if b1.get("time_origin_offset_ms") is not None:
        state.time_origin_ms = started + float(b1["time_origin_offset_ms"])
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
    try:
        generate_b1(state.to_b1_options(started))
        result["b1"] = True
    except Exception as exc:  # pragma: no cover
        result["errors"].append(f"b1: {exc}")

    try:
        generate_profile_data(
            fields=dict(profile.get("web_profile_fields") or {}),
            timestamp_ms=started,
            ets=started,
            document_cookie="ets=1; a1=00000000000000000000000000000000",
            time_origin=float(state.time_origin_ms),
            i12_seed=profile.get("web_profile_i12_seed"),
            telemetry_fi=profile.get("web_profile_fi"),
        )
        result["profileData"] = True
    except Exception as exc:  # pragma: no cover
        result["errors"].append(f"profileData: {exc}")
    return _finalize_validation(result)


def generate_fingerprint(
    *,
    target: str = "pc",
    seed: Optional[int] = None,
    validate: bool = True,
) -> GeneratedFingerprint:
    if target not in SUPPORTED_TARGETS:
        raise ValueError(f"unsupported fingerprint target: {target}")
    resolved_seed = int(seed) if seed is not None else random.SystemRandom().randint(1, 2_147_483_647)
    rng = _rng(resolved_seed, target)
    profile = _generate_creator(rng, resolved_seed) if target == "creator" else _generate_pc(rng, resolved_seed)
    validation: dict[str, Any] = {"profileData": None, "b1": None, "errors": []}
    if validate:
        validation = validate_profile(target, profile)
    profile["validation"] = validation
    return GeneratedFingerprint(target=target, seed=resolved_seed, profile=profile, validation=validation)


def build_summary(profile: Mapping[str, Any]) -> dict[str, Any]:
    navigator = profile.get("navigator") or {}
    display = profile.get("display") or {}
    browser = profile.get("browser") or {}
    os_info = profile.get("os") or {}
    return {
        "os": os_info.get("name", ""),
        "browser": browser.get("name", ""),
        "browserVersion": browser.get("fullVersion", ""),
        "userAgent": browser.get("userAgent", ""),
        "screen": f"{display.get('screenWidth', '?')}x{display.get('screenHeight', '?')}",
        "deviceScaleFactor": display.get("deviceScaleFactor"),
        "timezone": navigator.get("timezone", ""),
        "locale": navigator.get("locale", ""),
        "hardwareConcurrency": navigator.get("hardwareConcurrency"),
        "deviceMemory": navigator.get("deviceMemory"),
    }


def serialize_fingerprint(fingerprint: Any, account_count: int = 0) -> dict[str, Any]:
    try:
        summary = json.loads(fingerprint.summary_json or "{}")
    except json.JSONDecodeError:
        summary = {}
    try:
        profile = json.loads(fingerprint.profile_json or "{}")
    except json.JSONDecodeError:
        profile = {}
    return {
        "id": fingerprint.id,
        "name": fingerprint.name,
        "target": fingerprint.target,
        "seed": fingerprint.seed,
        "schema_version": fingerprint.schema_version,
        "summary": summary,
        "profile": profile,
        "validation": profile.get("validation") if isinstance(profile, dict) else None,
        "note": fingerprint.note,
        "account_count": account_count,
        "created_at": fingerprint.created_at.isoformat() if fingerprint.created_at else None,
        "updated_at": (fingerprint.updated_at or fingerprint.created_at).isoformat()
        if (fingerprint.updated_at or fingerprint.created_at)
        else None,
    }


__all__ = [
    "SCHEMA_VERSION",
    "SUPPORTED_TARGETS",
    "GeneratedFingerprint",
    "build_summary",
    "generate_fingerprint",
    "serialize_fingerprint",
    "validate_profile",
]

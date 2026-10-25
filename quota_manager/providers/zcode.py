from __future__ import annotations

import base64
import hashlib
import json
import os
import pwd
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from ..model import make_window, provider_payload
from ..util import now_ts, parse_retry_after, read_json, safe_error
from .base import Provider, ProviderError

DEFAULT_BASE_URL = "https://zcode.z.ai"
DEFAULT_APP_VERSION = "3.16.3"
_VERSION_CACHE: tuple[float, str] | None = None


def zcode_home() -> Path:
    override = os.environ.get("ZCODE_HOME")
    return Path(override).expanduser() if override else Path.home() / ".zcode"


def _credentials_path() -> Path:
    return zcode_home() / "v2" / "credentials.json"


def _onboarding_path() -> Path:
    return zcode_home() / "v2" / "onboarding-record.json"


def _b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _credential_secret() -> str:
    configured = os.environ.get("ZCODE_CREDENTIAL_SECRET", "").strip()
    if configured:
        return configured
    try:
        username = pwd.getpwuid(os.getuid()).pw_name
    except (KeyError, OSError):
        username = os.environ.get("USER") or "unknown"
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    return f"zcode-credential-fallback:{platform}:{Path.home()}:{username}"


def decrypt_credential(value: str) -> str:
    if not value.startswith("enc:v1:"):
        return value
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise ProviderError(
            "ZCode: нужен python3-cryptography для чтения локальной сессии."
        ) from exc
    parts = value[7:].split(".")
    if len(parts) != 3 or not all(parts):
        raise ProviderError("ZCode: повреждённая запись сессии.")
    iv, tag, ciphertext = (_b64url(part) for part in parts)
    if len(iv) != 12 or len(tag) != 16:
        raise ProviderError("ZCode: неподдерживаемый формат сессии.")
    key = hashlib.sha256(_credential_secret().encode("utf-8")).digest()
    try:
        plain = AESGCM(key).decrypt(iv, ciphertext + tag, None)
    except Exception as exc:
        raise ProviderError(
            "ZCode: не удалось расшифровать сессию. Перезапустите ZCode в том же профиле."
        ) from exc
    return plain.decode("utf-8")


def _running_zcode_version() -> str | None:
    for comm_path in Path("/proc").glob("[0-9]*/comm"):
        try:
            comm = comm_path.read_text(encoding="utf-8", errors="replace").strip().lower()
        except OSError:
            continue
        if "zcode" not in comm:
            continue
        environ_path = comm_path.with_name("environ")
        try:
            raw = environ_path.read_bytes()
        except OSError:
            continue
        match = re.search(rb"ZCODE_APP_VERSION=([^\x00]+)", raw)
        if match:
            try:
                return match.group(1).decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
    return None


def _version_from_appimage() -> str | None:
    candidates = [
        *Path.home().glob("Downloads/ZCode-*-linux-x64.AppImage"),
        *Path.home().glob(".local/bin/ZCode-*.AppImage"),
    ]
    version_re = re.compile(r"ZCode-([0-9]+(?:\.[0-9]+)+)-linux")
    for candidate in candidates:
        match = version_re.search(candidate.name)
        if match:
            return match.group(1)
    return None


def detect_app_version() -> str:
    global _VERSION_CACHE
    if _VERSION_CACHE and time.time() - _VERSION_CACHE[0] < 600:
        return _VERSION_CACHE[1]
    version = (
        os.environ.get("ZCODE_APP_VERSION", "").strip()
        or _running_zcode_version()
        or _version_from_appimage()
        or DEFAULT_APP_VERSION
    )
    _VERSION_CACHE = (time.time(), version)
    return version


def _device_mid() -> str:
    onboarding = read_json(_onboarding_path(), {})
    if isinstance(onboarding, dict):
        value = onboarding.get("deviceMid")
        if isinstance(value, str) and value.strip():
            return value.strip()
    identity = f"quota-grid:{os.getuid()}:{socket.gethostname()}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, identity))


def _base_url() -> str:
    candidate = os.environ.get("ZCODE_BASE_URL", "").strip() or DEFAULT_BASE_URL
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in ("https", "http"):
        return DEFAULT_BASE_URL
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        return DEFAULT_BASE_URL
    return candidate.rstrip("/")


def _json_error(payload: dict[str, Any]) -> str:
    message = payload.get("msg") or payload.get("message")
    if isinstance(message, str):
        return safe_error(message)
    error = payload.get("error")
    if isinstance(error, dict):
        return safe_error(error.get("message") or error.get("type") or "")
    return ""


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _select_windows(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str, str | None]:
    plans = [plan for plan in (data.get("plans") or []) if isinstance(plan, dict)]
    balances = [item for item in (data.get("balances") or []) if isinstance(item, dict)]
    entitlements: dict[str, dict[str, Any]] = {}
    active_plans = [plan for plan in plans if str(plan.get("status", "")).lower() == "active"]
    for plan in active_plans:
        for entitlement in plan.get("entitlements") or []:
            if isinstance(entitlement, dict) and entitlement.get("entitlement_id"):
                meta = dict(entitlement)
                meta["_plan_name"] = plan.get("name")
                meta["_plan_id"] = plan.get("plan_id")
                meta["_plan_ends_at"] = plan.get("ends_at")
                entitlements[str(entitlement["entitlement_id"])] = meta

    candidates: list[dict[str, Any]] = []
    for index, balance in enumerate(balances):
        entitlement_id = str(balance.get("entitlement_id") or "")
        total = _as_number(balance.get("total_units"))
        used = _as_number(balance.get("used_units"))
        remaining = _as_number(balance.get("remaining_units"))
        if total is None or total <= 0:
            continue
        if used is None:
            used = max(0.0, total - remaining) if remaining is not None else 0.0
        meta = entitlements.get(entitlement_id, {})
        period = str(meta.get("period") or balance.get("period") or "one_time").lower()
        priority = _as_number(meta.get("priority")) or 0.0
        show_name = str(balance.get("show_name") or meta.get("show_name") or "GLM").strip()
        resets_at = balance.get("period_end") or balance.get("expires_at") or meta.get("_plan_ends_at")
        try:
            resets_at_int = int(float(resets_at)) if resets_at else None
        except (TypeError, ValueError):
            resets_at_int = None
        candidates.append(
            {
                "id": f"zcode-{entitlement_id or index}",
                "show_name": show_name,
                "total": total,
                "used": used,
                "remaining": remaining,
                "period": period,
                "priority": priority,
                "resets_at": resets_at_int,
                "plan_name": str(meta.get("_plan_name") or ""),
            }
        )

    def best_by_model(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for candidate in items:
            name = candidate["show_name"]
            previous = best.get(name)
            if previous is None or candidate["priority"] > previous["priority"]:
                best[name] = candidate
        return sorted(best.values(), key=lambda item: item["show_name"])[:2]

    daily_chosen = best_by_model([item for item in candidates if item["period"] == "daily"])
    bonus_chosen = best_by_model([item for item in candidates if item["period"] == "one_time"])
    chosen = daily_chosen + bonus_chosen

    if not chosen:
        chosen = sorted(
            candidates,
            key=lambda item: (-item["priority"], item["resets_at"] or 2**62, item["show_name"]),
        )[:4]

    windows: list[dict[str, Any]] = []
    for candidate in chosen:
        total = candidate["total"]
        used = candidate["used"]
        remaining = candidate["remaining"]
        if remaining is None:
            remaining = max(0.0, total - used)
        used_percent = (used / total) * 100.0 if total else 0.0
        is_daily = candidate["period"] == "daily"
        windows.append(
            make_window(
                window_id=candidate["id"],
                title=candidate["show_name"],
                period_tag="DAY" if is_daily else "BONUS",
                period="daily" if is_daily else "one_time",
                used_percent=used_percent,
                resets_at=candidate["resets_at"],
                duration_minutes=1440 if is_daily else None,
                used_value=used,
                limit_value=total,
                remaining_value=remaining,
                unit="token",
            )
        )

    daily_plan = next(
        (
            plan
            for plan in active_plans
            if any(
                isinstance(entitlement, dict) and str(entitlement.get("period", "")).lower() == "daily"
                for entitlement in plan.get("entitlements") or []
            )
        ),
        active_plans[0] if active_plans else None,
    )
    plan_name = str((daily_plan or {}).get("name") or "ZCode").strip()
    account = re.sub(r"^ZCode\s+", "", plan_name, flags=re.IGNORECASE) or "ZCode"
    if "start plan" in plan_name.lower():
        badge = "START"
    elif "coding plan" in plan_name.lower():
        badge = "CODING"
    else:
        badge = "ZCODE"

    note = None
    bonus_names = [
        re.sub(r"^ZCode\s+", "", str(plan.get("name") or ""), flags=re.IGNORECASE)
        for plan in active_plans
        if any(
            isinstance(entitlement, dict) and str(entitlement.get("period", "")).lower() == "one_time"
            for entitlement in plan.get("entitlements") or []
        )
    ]
    if bonus_names:
        note = f"Бонус: {bonus_names[0]}"
    return windows, account, badge, note


class ZCodeProvider(Provider):
    id = "zcode"
    name = "ZCode"
    icon = "zcode"

    def detected(self) -> bool:
        raw = read_json(_credentials_path(), {})
        return isinstance(raw, dict) and bool(raw.get("zcodejwttoken"))

    def fetch(self) -> dict[str, Any]:
        raw = read_json(_credentials_path(), {})
        if not isinstance(raw, dict):
            raise ProviderError("ZCode: не найдена локальная сессия.", kind="auth")
        encrypted_jwt = raw.get("zcodejwttoken")
        if not isinstance(encrypted_jwt, str) or not encrypted_jwt:
            raise ProviderError("ZCode: не найден токен сессии. Войдите в ZCode.", kind="auth")
        jwt = decrypt_credential(encrypted_jwt)
        version = detect_app_version()
        device = _device_mid()
        query = urllib.parse.urlencode({"app_version": version})
        url = f"{_base_url()}/api/v1/zcode-plan/billing/balance?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {jwt}",
                "x-device-mid": device,
                "x-zcode-app-version": version,
                "Accept": "application/json",
                "User-Agent": f"ZCode/{version}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                status = response.status
                headers = {key.lower(): value for key, value in response.headers.items()}
                body = response.read()
        except urllib.error.HTTPError as exc:
            headers = {key.lower(): value for key, value in (exc.headers or {}).items()}
            status = exc.code
            body = exc.read()
        except urllib.error.URLError as exc:
            raise ProviderError("ZCode недоступен: проверьте интернет.") from exc

        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if status in (401, 403):
            raise ProviderError("ZCode: сессия истекла. Откройте ZCode и войдите снова.", kind="auth")
        if status == 429:
            retry_after = parse_retry_after(headers.get("retry-after"), 300)
            raise ProviderError(
                "ZCode временно ограничил запросы баланса.",
                kind="rate_limit",
                retry_after=retry_after,
            )
        if status != 200:
            detail = _json_error(payload)
            suffix = f" · {detail}" if detail else ""
            raise ProviderError(f"ZCode: ошибка API (HTTP {status}){suffix}.")
        if payload.get("code") not in (0, 200, None):
            detail = _json_error(payload)
            raise ProviderError(f"ZCode: {detail or 'не удалось получить баланс'}.")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ProviderError("ZCode не вернул данные о балансе.")
        windows, account, badge, note = _select_windows(data)
        if not windows:
            raise ProviderError("В ZCode нет активных пакетов с балансом.")
        return provider_payload(
            provider_id=self.id,
            name=self.name,
            icon=self.icon,
            account=account,
            badge=badge,
            windows=windows,
            fetched_at=now_ts(),
            note=note,
        )

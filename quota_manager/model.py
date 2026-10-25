from __future__ import annotations

from typing import Any

from . import __version__
from .util import clamp, now_ts

SCHEMA_VERSION = 1


def make_window(
    *,
    window_id: str,
    title: str,
    period_tag: str,
    period: str,
    used_percent: float,
    resets_at: int | None,
    duration_minutes: int | None = None,
    used_value: float | None = None,
    limit_value: float | None = None,
    remaining_value: float | None = None,
    unit: str = "percent",
) -> dict[str, Any]:
    used = round(clamp(float(used_percent)), 1)
    remaining = round(clamp(100.0 - used), 1)
    return {
        "id": window_id,
        "title": title,
        "period_tag": period_tag,
        "period": period,
        "used_percent": used,
        "remaining_percent": remaining,
        "resets_at": int(resets_at) if resets_at else None,
        "duration_minutes": duration_minutes,
        "used_value": used_value,
        "limit_value": limit_value,
        "remaining_value": remaining_value,
        "unit": unit,
    }


def provider_payload(
    *,
    provider_id: str,
    name: str,
    icon: str,
    account: str,
    badge: str,
    windows: list[dict[str, Any]],
    fetched_at: int,
    status: str = "ok",
    error: str | None = None,
    retry_at: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    return {
        "id": provider_id,
        "name": name,
        "icon": icon,
        "account": account,
        "badge": badge,
        "status": status,
        "error": error,
        "retry_at": retry_at,
        "note": note,
        "windows": windows,
        "fetched_at": fetched_at,
        "last_attempt_at": now_ts(),
    }


def empty_snapshot(interval: int = 300) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "app_version": __version__,
        "generated_at": 0,
        "next_refresh_at": None,
        "interval_seconds": interval,
        "status": "empty",
        "providers": [],
        "recent_resets": [],
    }

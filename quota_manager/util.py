from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


def _xdg_home(env_name: str, fallback: str) -> Path:
    value = os.environ.get(env_name)
    if value:
        return Path(value).expanduser()
    return Path.home() / fallback


def data_dir() -> Path:
    override = os.environ.get("QUOTA_MANAGER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _xdg_home("XDG_DATA_HOME", ".local/share") / "quota-manager"


def state_dir() -> Path:
    override = os.environ.get("QUOTA_MANAGER_STATE_DIR")
    if override:
        return Path(override).expanduser()
    return _xdg_home("XDG_STATE_HOME", ".local/state") / "quota-manager"


def config_dir() -> Path:
    override = os.environ.get("QUOTA_MANAGER_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return _xdg_home("XDG_CONFIG_HOME", ".config") / "quota-manager"


def cache_path() -> Path:
    return data_dir() / "snapshot.json"


def reset_state_path() -> Path:
    return state_dir() / "resets.json"


def lock_path() -> Path:
    return state_dir() / "refresh.lock"


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def atomic_write_json(path: Path, payload: Any, mode: int = 0o600) -> None:
    ensure_private_dir(path.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def now_ts() -> int:
    return int(time.time())


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def parse_timestamp(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            return None
        if number > 10_000_000_000:
            number /= 1000.0
        return int(number)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            pass
        else:
            return parse_timestamp(number)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


def parse_retry_after(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        seconds = int(float(text))
        return max(1, seconds)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(1, int(parsed.timestamp() - time.time()))
    except (TypeError, ValueError):
        return default


_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)((?:access|refresh|id|api)?[_-]?token[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}]+"
    ),
    re.compile(r"(?i)((?:api[_-]?key|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',;}]+"),
    re.compile(r"(?i)((?:authorization|cookie)[\"']?\s*[:=]\s*)[^\s,;}]+"),
    re.compile(r"\b(?:sk|xox[baprs])-[A-Za-z0-9_-]{12,}\b"),
)


def safe_error(message: Any, limit: int = 320) -> str:
    text = str(message or "").strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "<redacted>", text)
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def display_plan_name(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.replace("_", " ").replace("-", " ").strip()
    return " ".join(part.capitalize() for part in cleaned.split())


def load_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "refresh_interval_seconds": 300,
        "notifications": True,
    }
    raw = read_json(config_dir() / "config.json", {})
    if isinstance(raw, dict):
        interval = raw.get("refresh_interval_seconds")
        if isinstance(interval, (int, float)) and not isinstance(interval, bool):
            defaults["refresh_interval_seconds"] = min(3600, max(60, int(interval)))
        if isinstance(raw.get("notifications"), bool):
            defaults["notifications"] = raw["notifications"]
    return defaults

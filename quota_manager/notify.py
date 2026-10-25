from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


def _icon_path() -> str:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    installed = data_home / "icons/hicolor/scalable/apps/quota-grid.svg"
    if installed.is_file():
        return str(installed)
    return "quota-grid"


def notify(title: str, body: str, *, timeout_ms: int = 12_000) -> bool:
    binary = shutil.which("notify-send")
    if not binary:
        LOG.warning("notify-send is not available; notification skipped")
        return False
    command = [
        binary,
        "--app-name=Quota Grid",
        f"--icon={_icon_path()}",
        "--urgency=normal",
        f"--expire-time={timeout_ms}",
        "--category=device",
        title,
        body,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=8,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("notification failed: %s", type(exc).__name__)
        return False
    if result.returncode != 0:
        LOG.warning("notification failed with exit code %s", result.returncode)
        return False
    return True


def notify_resets(provider_name: str, windows: list[dict[str, Any]]) -> bool:
    labels: list[str] = []
    for window in windows:
        label = str(window.get("title") or "Лимит")
        if label not in labels:
            labels.append(label)
    if not labels:
        return False
    title = f"{provider_name}: лимиты сброшены"
    body = "Новый период: " + ", ".join(labels) + "."
    return notify(title, body)


def send_test_notification() -> bool:
    return notify(
        "Quota Grid подключён",
        "Системные уведомления о сбросе лимитов AI-инструментов включены.",
    )

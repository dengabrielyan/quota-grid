from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .util import atomic_write_json, config_dir

DEFAULT_CONFIG = {
    "refresh_interval_seconds": 300,
    "notifications": True,
}


def ensure_config() -> Path:
    path = config_dir() / "config.json"
    if not path.exists():
        atomic_write_json(path, DEFAULT_CONFIG)
    return path


def open_settings_file() -> tuple[int, str]:
    path = ensure_config()
    opener = shutil.which("xdg-open")
    if not opener:
        return 0, str(path)
    try:
        subprocess.Popen(
            [opener, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return 1, str(path)
    return 0, str(path)

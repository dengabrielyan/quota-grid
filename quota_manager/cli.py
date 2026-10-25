from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from typing import Any

from . import APP_NAME, __version__
from .daemon import run_daemon
from .notify import send_test_notification
from .orchestrator import refresh, status
from .providers import ALL_PROVIDERS
from .providers.claude import claude_config_dir
from .providers.codex import _find_codex_binary, codex_home
from .providers.zcode import _credentials_path as zcode_credentials_path
from .providers.zcode import detect_app_version
from .settings import open_settings_file
from .util import data_dir, load_config, read_json


def _format_delta(seconds: int) -> str:
    if seconds <= 0:
        return "сейчас"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{max(1, minutes)} мин"


def _format_reset(timestamp: Any) -> str:
    if not isinstance(timestamp, (int, float)) or timestamp <= 0:
        return "без сброса"
    now = int(time.time())
    if timestamp <= now:
        return "обновлено"
    return f"через {_format_delta(int(timestamp) - now)}"


def _print_human(snapshot: dict[str, Any]) -> None:
    generated = snapshot.get("generated_at")
    if generated:
        stamp = time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(generated))
    else:
        stamp = "ещё не было"
    current_status = str(snapshot.get("status") or "empty").upper()
    print(f"{APP_NAME} {__version__} · {current_status} · обновлено: {stamp}")
    providers = snapshot.get("providers") or []
    if not providers:
        print("\nАктивные AI-инструменты не найдены.")
        print("Поддерживаются Claude Code, Codex CLI и ZCode Desktop.")
        return
    for provider in providers:
        header = provider.get("name") or provider.get("id")
        account = provider.get("account")
        badge = provider.get("badge")
        parts = [str(header)]
        if account:
            parts.append(str(account))
        if badge and str(badge).lower() not in str(account).lower():
            parts.append(str(badge))
        print("\n" + " · ".join(parts))
        if provider.get("error"):
            print(f"  ! {provider['error']}")
        for window in provider.get("windows") or []:
            percent = float(window.get("remaining_percent") or 0)
            tag = str(window.get("period_tag") or "")
            title = str(window.get("title") or "")
            reset = _format_reset(window.get("resets_at"))
            count = ""
            if window.get("unit") == "token" and isinstance(window.get("used_value"), (int, float)):
                used = float(window["used_value"])
                limit = window.get("limit_value")
                count = f" · {used / 1_000_000:.2f}M"
                if isinstance(limit, (int, float)) and limit:
                    count += f" / {float(limit) / 1_000_000:.2f}M"
            print(f"  [{tag:<5}] {title:<18} осталось {percent:5.1f}%{count} · {reset}")
        if provider.get("note"):
            print(f"  {provider['note']}")


def _output(snapshot: dict[str, Any], as_json: bool) -> None:
    if as_json:
        json.dump(snapshot, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print_human(snapshot)


def _doctor() -> int:
    config = load_config()
    print(f"{APP_NAME} {__version__}")
    print(f"data:   {data_dir()}")
    print(f"refresh interval: {config['refresh_interval_seconds']}s")
    print(f"notifications: {'on' if config['notifications'] else 'off'}")
    print("\nProviders:")
    for provider_type in ALL_PROVIDERS:
        instance = provider_type()
        try:
            detected = instance.detected()
        except Exception:
            detected = False
        print(f"  {instance.name:<12} {'detected' if detected else 'not found'}")
    print("\nDetails:")
    claude_creds = claude_config_dir() / ".credentials.json"
    claude_data = read_json(claude_creds, {})
    claude_oauth = claude_data.get("claudeAiOauth") if isinstance(claude_data, dict) else {}
    if isinstance(claude_oauth, dict) and claude_oauth:
        expires = claude_oauth.get("expiresAt")
        expires_text = "unknown"
        if isinstance(expires, (int, float)):
            expires_text = time.strftime("%d.%m.%Y %H:%M", time.localtime(expires / 1000))
        print(f"  claude credentials: {claude_creds} (access expires {expires_text})")
    else:
        print(f"  claude credentials: not found ({claude_creds})")
    codex_bin = _find_codex_binary()
    print(f"  codex binary: {codex_bin or 'not found'}")
    print(f"  codex home: {codex_home()}")
    zcode_path = zcode_credentials_path()
    print(f"  zcode credentials: {'found' if zcode_path.is_file() else 'not found'} ({zcode_path})")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401

        crypto = "available"
    except ImportError:
        crypto = "MISSING (apt install python3-cryptography)"
    print(f"  zcode crypto: {crypto}")
    print(f"  zcode app version: {detect_app_version()}")
    notify_bin = shutil.which("notify-send")
    print(f"  notify-send: {notify_bin or 'not found'}")
    return 0


def _open_settings() -> int:
    code, path = open_settings_file()
    print(path)
    return code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quota-manager", description=f"{APP_NAME}: AI quota monitor")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser("status", help="show cached quota state")
    status_parser.add_argument("--json", action="store_true", help="machine-readable output")

    refresh_parser = subparsers.add_parser("refresh", help="refresh all quotas now")
    refresh_parser.add_argument("--json", action="store_true", help="machine-readable output")
    refresh_parser.add_argument("--notify", action="store_true", help="send reset notifications")
    refresh_parser.add_argument("--force", action="store_true", help="ignore retry cooldowns")

    subparsers.add_parser("daemon", help="run the background collector")

    ui_parser = subparsers.add_parser("ui", help="run the cross-desktop web dashboard")
    ui_parser.add_argument("--port", type=int, default=0, help="local port (0 chooses a free port)")
    ui_parser.add_argument("--no-browser", action="store_true", help="do not open a browser")

    subparsers.add_parser("doctor", help="show provider and dependency diagnostics")
    subparsers.add_parser("notify-test", help="send a test system notification")
    subparsers.add_parser("settings", help="create and open the config file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "status"
    try:
        if command == "status":
            _output(status(), bool(getattr(args, "json", False)))
            return 0
        if command == "refresh":
            snapshot = refresh(
                notify=bool(getattr(args, "notify", False)),
                ignore_cooldown=bool(getattr(args, "force", False)),
            )
            _output(snapshot, bool(getattr(args, "json", False)))
            return 0
        if command == "daemon":
            return run_daemon()
        if command == "ui":
            from .web import serve_ui

            return serve_ui(
                port=int(getattr(args, "port", 0) or 0),
                open_browser=not bool(getattr(args, "no_browser", False)),
            )
        if command == "doctor":
            return _doctor()
        if command == "notify-test":
            ok = send_test_notification()
            print("Уведомление отправлено." if ok else "Не удалось отправить уведомление.")
            return 0 if ok else 1
        if command == "settings":
            return _open_settings()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from .. import __version__
from ..model import make_window, provider_payload
from ..util import now_ts, read_json, safe_error
from .base import Provider, ProviderError


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    return Path(override).expanduser() if override else Path.home() / ".codex"


def _find_codex_binary() -> str | None:
    candidates = [
        os.environ.get("CODEX_BIN"),
        shutil.which("codex"),
        str(Path.home() / ".local/bin/codex"),
        "/usr/local/bin/codex",
        "/usr/bin/codex",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _label_for_window(minutes: int | None) -> tuple[str, str, str]:
    if minutes == 300:
        return "5 часов", "5H", "rolling_5h"
    if minutes == 10080:
        return "Неделя", "7D", "weekly"
    if minutes == 1440:
        return "Сутки", "1D", "daily"
    if minutes is None or minutes <= 0:
        return "Лимит", "—", "window"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} дн.", f"{days}D", "window"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} ч.", f"{hours}H", "window"
    return f"{minutes} мин.", f"{minutes}M", "window"


class _AppServerSession:
    def __init__(self, binary: str, timeout: float = 25.0) -> None:
        self.binary = binary
        self.timeout = timeout
        self.process: subprocess.Popen[bytes] | None = None
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.stderr: queue.Queue[str] = queue.Queue()

    def __enter__(self) -> "_AppServerSession":
        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        self.process = subprocess.Popen(
            [self.binary, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        return self

    def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if isinstance(payload, dict):
                    self.messages.put(payload)
        finally:
            self.messages.put(None)

    def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        try:
            while True:
                line = self.process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", "replace").strip()
                if text:
                    self.stderr.put(text)
        except (OSError, ValueError):
            pass

    def send(self, payload: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.process.stdin.flush()

    def wait_for_id(self, request_id: int, timeout: float | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("codex app-server timeout")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError("codex app-server timeout") from exc
            if message is None:
                raise ProviderError("Codex app-server завершился неожиданно.")
            if message.get("id") == request_id:
                return message

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        process = self.process
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        for stream in (process.stdout, process.stderr):
            try:
                if stream:
                    stream.close()
            except (OSError, ValueError):
                pass


class CodexProvider(Provider):
    id = "codex"
    name = "Codex"
    icon = "codex"

    def detected(self) -> bool:
        auth = read_json(codex_home() / "auth.json", {})
        return isinstance(auth, dict) and bool(auth.get("tokens") or auth.get("auth_mode") == "chatgpt")

    def fetch(self) -> dict[str, Any]:
        binary = _find_codex_binary()
        if not binary:
            raise ProviderError("Codex CLI не найден в PATH.")
        try:
            with _AppServerSession(binary) as session:
                session.send(
                    {
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "clientInfo": {
                                "name": "quota-grid",
                                "title": "Quota Grid",
                                "version": __version__,
                            },
                            "capabilities": {"experimentalApi": True},
                        },
                    }
                )
                init = session.wait_for_id(1, timeout=18)
                if "error" in init:
                    message = (init.get("error") or {}).get("message") or "Codex отклонил подключение."
                    raise ProviderError(safe_error(message))
                session.send({"method": "initialized", "params": {}})
                session.send({"id": 2, "method": "account/rateLimits/read", "params": {}})
                response = session.wait_for_id(2, timeout=20)
        except TimeoutError as exc:
            raise ProviderError("Codex не ответил на запрос лимитов.") from exc
        except OSError as exc:
            raise ProviderError("Не удалось запустить Codex CLI.") from exc

        if "error" in response:
            error = response.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else None
            raise ProviderError(safe_error(message or "Codex вернул ошибку авторизации."))

        result = response.get("result") or {}
        rate = result.get("rateLimits")
        if not isinstance(rate, dict):
            by_id = result.get("rateLimitsByLimitId")
            if isinstance(by_id, dict) and by_id:
                rate = next(iter(by_id.values()), None)
        if not isinstance(rate, dict):
            raise ProviderError("Codex не вернул данные о лимитах.")

        windows: list[dict[str, Any]] = []
        for index, key in enumerate(("primary", "secondary")):
            item = rate.get(key)
            if not isinstance(item, dict):
                continue
            used = item.get("usedPercent", item.get("used_percent"))
            if not isinstance(used, (int, float)):
                continue
            minutes = item.get("windowDurationMins", item.get("window_duration_mins"))
            try:
                minutes_int = int(minutes) if minutes is not None else None
            except (TypeError, ValueError):
                minutes_int = None
            title, tag, period = _label_for_window(minutes_int)
            resets_at = item.get("resetsAt", item.get("resets_at"))
            windows.append(
                make_window(
                    window_id=key if key else f"window-{index}",
                    title=title,
                    period_tag=tag,
                    period=period,
                    used_percent=float(used),
                    resets_at=int(resets_at) if isinstance(resets_at, (int, float)) else None,
                    duration_minutes=minutes_int,
                )
            )

        if not windows:
            raise ProviderError("Codex не вернул активных окон квоты.")

        plan = str(rate.get("planType") or rate.get("plan_type") or "").strip()
        plan_name = plan.title()
        account = f"ChatGPT {plan_name}".strip() if plan_name else "Codex"
        note = None
        reached = rate.get("rateLimitReachedType")
        if reached:
            note = f"Ограничение: {str(reached).replace('_', ' ')}"
        return provider_payload(
            provider_id=self.id,
            name=self.name,
            icon=self.icon,
            account=account,
            badge=plan.upper() if plan else "CODEX",
            windows=windows,
            fetched_at=now_ts(),
            note=note,
        )

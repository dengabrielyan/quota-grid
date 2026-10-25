from __future__ import annotations

import html
import json
import secrets
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import APP_NAME, __version__
from .orchestrator import refresh, status
from .settings import open_settings_file

WEB_DIR = Path(__file__).with_name("webui")
TOKEN_HEADER = "X-Quota-Token"
IDLE_TIMEOUT_SECONDS = 300

STATIC_FILES: dict[str, tuple[str, str]] = {
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/quota-grid-mark.svg": ("assets/quota-grid-mark.svg", "image/svg+xml"),
    "/assets/refresh.svg": ("assets/refresh.svg", "image/svg+xml"),
    "/assets/gear.svg": ("assets/gear.svg", "image/svg+xml"),
}

PROVIDER_ICONS = {
    "claude": "assets/icons/claude.png",
    "codex": "assets/icons/codex.png",
    "zcode": "assets/icons/zcode.png",
}


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class QuotaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], token: str) -> None:
        super().__init__(server_address, QuotaRequestHandler)
        self.auth_token = token
        self.last_activity = time.monotonic()

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}/"


class QuotaRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "QuotaGrid"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _host_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        name, separator, port = host.partition(":")
        if name not in ("127.0.0.1", "localhost"):
            return False
        if separator and port != str(self.server.server_address[1]):
            return False
        return True

    def _authorized(self) -> bool:
        supplied = self.headers.get(TOKEN_HEADER, "")
        return secrets.compare_digest(supplied, self.server.auth_token)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.server.last_activity = time.monotonic()
        self.send_response(code)
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, _json_bytes(payload), "application/json; charset=utf-8")

    def _error(self, code: int, message: str) -> None:
        self._json(code, {"error": message})

    def _serve_index(self) -> None:
        try:
            markup = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        except OSError:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось загрузить интерфейс.")
            return
        markup = markup.replace("__QUOTA_TOKEN__", html.escape(self.server.auth_token, quote=True))
        markup = markup.replace("__APP_VERSION__", html.escape(__version__))
        self._send(HTTPStatus.OK, markup.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_asset(self, path: str) -> bool:
        relative = STATIC_FILES.get(path)
        if relative is None and path.startswith("/assets/icons/"):
            icon_name = path.rsplit("/", 1)[-1]
            if icon_name.endswith(".png") and icon_name[:-4] in PROVIDER_ICONS:
                relative = (PROVIDER_ICONS[icon_name[:-4]], "image/png")
        if relative is None:
            return False
        file_name, content_type = relative
        try:
            body = (WEB_DIR / file_name).read_bytes()
        except OSError:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось загрузить ресурс.")
            return True
        self._send(HTTPStatus.OK, body, content_type)
        return True

    def do_GET(self) -> None:
        if not self._host_allowed():
            self._error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._serve_index()
            return
        if self._serve_asset(path):
            return
        if path == "/api/status":
            if not self._authorized():
                self._error(HTTPStatus.FORBIDDEN, "Forbidden")
                return
            try:
                self._json(HTTPStatus.OK, status())
            except Exception:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось прочитать квоты.")
            return
        self._error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        if not self._host_allowed():
            self._error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not self._authorized():
            self._error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "Bad request")
            return
        if length > 65_536:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large")
            return
        if length:
            try:
                self.rfile.read(length)
            except OSError:
                pass
        path = urlsplit(self.path).path
        if path == "/api/refresh":
            try:
                self._json(HTTPStatus.OK, refresh(notify=False))
            except Exception:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось обновить квоты.")
            return
        if path == "/api/settings":
            try:
                code, settings_path = open_settings_file()
            except Exception:
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Не удалось открыть настройки.")
                return
            self._json(HTTPStatus.OK, {"ok": code == 0, "path": settings_path})
            return
        self._error(HTTPStatus.NOT_FOUND, "Not found")


def create_server(port: int = 0, token: str | None = None) -> QuotaHTTPServer:
    if not 0 <= port <= 65_535:
        raise ValueError("port must be between 0 and 65535")
    server = QuotaHTTPServer(("127.0.0.1", port), token or secrets.token_urlsafe(32))
    return server


def _start_initial_refresh() -> None:
    try:
        if not status().get("generated_at"):
            refresh(notify=False)
    except Exception:
        pass


def _idle_watchdog(server: QuotaHTTPServer, timeout: int) -> None:
    while True:
        time.sleep(15)
        if time.monotonic() - server.last_activity > timeout:
            server.shutdown()
            return


def serve_ui(*, port: int = 0, open_browser: bool = True) -> int:
    try:
        server = create_server(port)
    except (OSError, ValueError) as exc:
        print(f"{APP_NAME}: не удалось запустить локальный интерфейс: {exc}")
        return 1

    url = server.url
    print(f"{APP_NAME} {__version__}")
    print(f"Интерфейс: {url}")
    print("Нажмите Ctrl+C, чтобы остановить.")

    threading.Thread(target=_start_initial_refresh, daemon=True).start()
    threading.Thread(target=_idle_watchdog, args=(server, IDLE_TIMEOUT_SECONDS), daemon=True).start()

    if open_browser:
        def launch_browser() -> None:
            try:
                webbrowser.open(url, new=2)
            except Exception:
                pass

        threading.Timer(0.4, launch_browser).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0

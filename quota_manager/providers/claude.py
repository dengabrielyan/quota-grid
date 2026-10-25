from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..model import make_window, provider_payload
from ..util import (
    atomic_write_json,
    display_plan_name,
    now_ts,
    parse_retry_after,
    parse_timestamp,
    read_json,
    safe_error,
)
from .base import Provider, ProviderError

TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_BETA = "oauth-2025-04-20"
USER_AGENT = "claude-cli/2.1.296 (external, cli)"


def claude_config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def _credentials_path() -> Path:
    return claude_config_dir() / ".credentials.json"


def _request_json(
    url: str,
    *,
    headers: dict[str, str],
    method: str = "GET",
    body: bytes | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            payload = json.loads(raw.decode("utf-8") or "{}")
            return response.status, payload, response_headers
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        payload: dict[str, Any] = {}
        try:
            decoded = json.loads(raw.decode("utf-8") or "{}")
            if isinstance(decoded, dict):
                payload = decoded
        except ValueError:
            pass
        response_headers = {key.lower(): value for key, value in (exc.headers or {}).items()}
        return exc.code, payload, response_headers
    except urllib.error.URLError as exc:
        raise ProviderError("Claude недоступен: проверьте интернет.") from exc


def _oauth_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return safe_error(error.get("message") or error.get("type") or "")
    if isinstance(error, str):
        return safe_error(error)
    return ""


class ClaudeProvider(Provider):
    id = "claude"
    name = "Claude Code"
    icon = "claude"

    def detected(self) -> bool:
        data = read_json(_credentials_path(), {})
        oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
        return isinstance(oauth, dict) and bool(oauth.get("accessToken") or oauth.get("refreshToken"))

    def _refresh(self, oauth: dict[str, Any]) -> dict[str, Any]:
        refresh_token = oauth.get("refreshToken")
        if not refresh_token:
            raise ProviderError("Claude Code: нет refresh-токена. Выполните `claude auth login`.", kind="auth")
        body = urllib.parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CLIENT_ID,
            }
        ).encode("utf-8")
        status, payload, headers = _request_json(
            TOKEN_URL,
            method="POST",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "anthropic-beta": OAUTH_BETA,
            },
        )
        if status != 200:
            retry_after = parse_retry_after(headers.get("retry-after"), 900 if status == 429 else None)
            detail = _oauth_error_message(payload)
            error_code = str(payload.get("error") or "")
            if status in (400, 401, 403) or error_code == "invalid_grant":
                raise ProviderError(
                    "Claude Code: сессия больше не действительна. Выполните `claude auth login`.",
                    kind="auth",
                )
            if status == 429:
                raise ProviderError(
                    "Claude: OAuth временно ограничил обновление сессии (HTTP 429).",
                    kind="rate_limit",
                    retry_after=retry_after,
                )
            suffix = f" ({detail})" if detail else ""
            raise ProviderError(
                f"Claude: не удалось обновить сессию (HTTP {status}){suffix}.",
                retry_after=retry_after,
            )

        access = payload.get("access_token")
        if not access:
            raise ProviderError("Claude вернул некорректный ответ при обновлении сессии.", kind="auth")
        new_refresh = payload.get("refresh_token") or refresh_token
        expires_in = payload.get("expires_in")
        try:
            expires_seconds = float(expires_in) if expires_in is not None else 28_800.0
        except (TypeError, ValueError):
            expires_seconds = 28_800.0
        expires_at = int((time.time() + expires_seconds) * 1000) - 30_000
        refresh_expires_at = oauth.get("refreshTokenExpiresAt")
        if payload.get("refresh_token_expires_in") is not None:
            try:
                refresh_expires_at = int(
                    (time.time() + float(payload["refresh_token_expires_in"])) * 1000
                ) - 30_000
            except (TypeError, ValueError):
                pass

        self._save_refreshed(access, new_refresh, expires_at, refresh_expires_at)
        updated = dict(oauth)
        updated.update(
            {
                "accessToken": access,
                "refreshToken": new_refresh,
                "expiresAt": expires_at,
            }
        )
        if refresh_expires_at:
            updated["refreshTokenExpiresAt"] = refresh_expires_at
        return updated

    def _save_refreshed(
        self,
        access: str,
        refresh: str,
        expires_at: int,
        refresh_expires_at: int | None,
    ) -> None:
        path = _credentials_path()
        latest = read_json(path, {})
        if not isinstance(latest, dict):
            latest = {}
        oauth = latest.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            oauth = {}
        oauth.update(
            {
                "accessToken": access,
                "refreshToken": refresh,
                "expiresAt": expires_at,
            }
        )
        if refresh_expires_at:
            oauth["refreshTokenExpiresAt"] = refresh_expires_at
        latest["claudeAiOauth"] = oauth
        atomic_write_json(path, latest, mode=0o600)

    def _fetch_usage(self, access_token: str) -> tuple[int, dict[str, Any], dict[str, str]]:
        return _request_json(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "anthropic-beta": OAUTH_BETA,
            },
        )

    @staticmethod
    def _usage_window(
        payload: dict[str, Any],
        key: str,
        *,
        window_id: str,
        title: str,
        tag: str,
        period: str,
        duration_minutes: int,
    ) -> dict[str, Any] | None:
        item = payload.get(key)
        if not isinstance(item, dict):
            return None
        used = item.get("utilization", item.get("used_percent"))
        if not isinstance(used, (int, float)):
            return None
        # The OAuth usage endpoint exposes utilization as a percentage.
        used_percent = float(used)
        if 0 < used_percent < 1:
            used_percent *= 100.0
        return make_window(
            window_id=window_id,
            title=title,
            period_tag=tag,
            period=period,
            used_percent=used_percent,
            resets_at=parse_timestamp(item.get("resets_at")),
            duration_minutes=duration_minutes,
        )

    def fetch(self) -> dict[str, Any]:
        data = read_json(_credentials_path(), {})
        oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
        if not isinstance(oauth, dict):
            raise ProviderError("Claude Code: не найдена OAuth-сессия.", kind="auth")

        access = oauth.get("accessToken")
        expires_at = oauth.get("expiresAt")
        expired = not isinstance(expires_at, (int, float)) or expires_at <= time.time() * 1000 + 120_000
        refreshed = False
        if expired or not access:
            oauth = self._refresh(oauth)
            access = oauth["accessToken"]
            refreshed = True

        status, payload, headers = self._fetch_usage(str(access))
        if status == 401 and not refreshed:
            oauth = self._refresh(oauth)
            access = oauth["accessToken"]
            status, payload, headers = self._fetch_usage(str(access))

        if status != 200:
            retry_after = parse_retry_after(headers.get("retry-after"), 300 if status == 429 else None)
            detail = _oauth_error_message(payload)
            if status in (401, 403):
                raise ProviderError(
                    "Claude Code: сессия истекла. Выполните `claude auth login`.",
                    kind="auth",
                )
            if status == 429:
                raise ProviderError(
                    "Claude: сервис временно ограничил запросы квот (HTTP 429).",
                    kind="rate_limit",
                    retry_after=retry_after,
                )
            suffix = f" · {detail}" if detail else ""
            raise ProviderError(f"Claude: ошибка API (HTTP {status}){suffix}.")

        windows = [
            window
            for window in (
                self._usage_window(
                    payload,
                    "five_hour",
                    window_id="five_hour",
                    title="5 часов",
                    tag="5H",
                    period="rolling_5h",
                    duration_minutes=300,
                ),
                self._usage_window(
                    payload,
                    "seven_day",
                    window_id="seven_day",
                    title="Неделя",
                    tag="7D",
                    period="weekly",
                    duration_minutes=10080,
                ),
            )
            if window is not None
        ]
        if not windows:
            raise ProviderError("Claude не вернул данные о лимитах.")

        subscription = str(oauth.get("subscriptionType") or "").strip()
        plan = display_plan_name(subscription) if subscription else ""
        account = f"Claude {plan}".strip()
        return provider_payload(
            provider_id=self.id,
            name=self.name,
            icon=self.icon,
            account=account or "Claude",
            badge=subscription.upper() if subscription else "CLAUDE",
            windows=windows,
            fetched_at=now_ts(),
        )

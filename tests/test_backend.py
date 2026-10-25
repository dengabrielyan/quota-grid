from __future__ import annotations

import base64
import hashlib
import os
import unittest
from unittest.mock import patch

from quota_manager.model import make_window
from quota_manager.orchestrator import _provider_summary, _record_resets
from quota_manager.providers.claude import ClaudeProvider
from quota_manager.providers.codex import _label_for_window
from quota_manager.providers.zcode import _select_windows, decrypt_credential
from quota_manager.util import parse_retry_after, parse_timestamp, safe_error


class ModelTests(unittest.TestCase):
    def test_window_clamps_and_derives_remaining(self) -> None:
        window = make_window(
            window_id="five_hour",
            title="5 часов",
            period_tag="5H",
            period="rolling_5h",
            used_percent=142.0,
            resets_at=123,
        )
        self.assertEqual(window["used_percent"], 100.0)
        self.assertEqual(window["remaining_percent"], 0.0)
        self.assertEqual(window["resets_at"], 123)

    def test_provider_summary(self) -> None:
        self.assertEqual(_provider_summary([]), "empty")
        self.assertEqual(_provider_summary([{"status": "ok"}]), "ok")
        self.assertEqual(_provider_summary([{"status": "ok"}, {"status": "error"}]), "degraded")
        self.assertEqual(_provider_summary([{"status": "error"}]), "error")


class UtilityTests(unittest.TestCase):
    def test_parse_iso_timestamp(self) -> None:
        self.assertEqual(parse_timestamp("2026-10-25T07:00:00.180626+00:00"), 1792911600)
        self.assertIsNone(parse_timestamp(None))
        self.assertEqual(parse_timestamp(1792911600), 1792911600)

    def test_parse_retry_after(self) -> None:
        self.assertEqual(parse_retry_after("42"), 42)
        self.assertEqual(parse_retry_after(None, 900), 900)

    def test_secrets_are_redacted(self) -> None:
        message = "Authorization: Bearer abcdef123456 and token=secret-value"
        cleaned = safe_error(message)
        self.assertNotIn("abcdef123456", cleaned)
        self.assertNotIn("secret-value", cleaned)
        self.assertIn("<redacted>", cleaned)


class ClaudeTests(unittest.TestCase):
    def test_usage_window_parses_percentage_and_reset(self) -> None:
        provider = ClaudeProvider()
        window = provider._usage_window(
            {
                "five_hour": {
                    "utilization": 42.5,
                    "resets_at": "2026-10-24T20:00:00Z",
                }
            },
            "five_hour",
            window_id="five_hour",
            title="5 часов",
            tag="5H",
            period="rolling_5h",
            duration_minutes=300,
        )
        self.assertIsNotNone(window)
        assert window is not None
        self.assertEqual(window["used_percent"], 42.5)
        self.assertEqual(window["remaining_percent"], 57.5)
        self.assertEqual(window["resets_at"], 1792872000)

    def test_usage_window_treats_fraction_as_fraction(self) -> None:
        provider = ClaudeProvider()
        window = provider._usage_window(
            {"seven_day": {"utilization": 0.5}},
            "seven_day",
            window_id="seven_day",
            title="Неделя",
            tag="7D",
            period="weekly",
            duration_minutes=10080,
        )
        assert window is not None
        self.assertEqual(window["used_percent"], 50.0)


class CodexTests(unittest.TestCase):
    def test_window_labels(self) -> None:
        self.assertEqual(_label_for_window(300)[1], "5H")
        self.assertEqual(_label_for_window(10080)[1], "7D")
        self.assertEqual(_label_for_window(1440)[1], "1D")

    def test_zero_duration_does_not_crash(self) -> None:
        title, tag, period = _label_for_window(None)
        self.assertEqual(title, "Лимит")
        self.assertEqual(tag, "—")
        self.assertEqual(period, "window")


class ZCodeTests(unittest.TestCase):
    def test_selects_daily_windows_and_builds_metadata(self) -> None:
        plans = [
            {
                "name": "ZCode 1024 Dev Day",
                "plan_id": "bonus",
                "status": "active",
                "ends_at": 2_000_000_000,
                "entitlements": [
                    {
                        "entitlement_id": "bonus-flash",
                        "show_name": "GLM-5.3-Flash",
                        "period": "one_time",
                        "priority": 101,
                    },
                    {
                        "entitlement_id": "bonus-main",
                        "show_name": "GLM-5.3",
                        "period": "one_time",
                        "priority": 100,
                    }
                ],
            },
            {
                "name": "ZCode Start Plan",
                "plan_id": "start",
                "status": "active",
                "entitlements": [
                    {
                        "entitlement_id": "daily-main",
                        "show_name": "GLM-5.3",
                        "period": "daily",
                        "priority": 110,
                    },
                    {
                        "entitlement_id": "daily-flash",
                        "show_name": "GLM-5.3-Flash",
                        "period": "daily",
                        "priority": 80,
                    },
                ],
            },
        ]
        balances = [
            {
                "entitlement_id": "bonus-flash",
                "show_name": "GLM-5.3-Flash",
                "total_units": 300_000_000,
                "used_units": 20_000_000,
                "remaining_units": 280_000_000,
                "expires_at": 2_000_000_000,
            },
            {
                "entitlement_id": "bonus-main",
                "show_name": "GLM-5.3",
                "total_units": 200_000_000,
                "used_units": 20_000_000,
                "remaining_units": 180_000_000,
                "expires_at": 2_000_000_000,
            },
            {
                "entitlement_id": "daily-main",
                "show_name": "GLM-5.3",
                "total_units": 3_000_000,
                "used_units": 2_500_000,
                "remaining_units": 500_000,
                "period_start": 1_700_000_000,
                "period_end": 1_700_086_400,
            },
            {
                "entitlement_id": "daily-flash",
                "show_name": "GLM-5.3-Flash",
                "total_units": 5_000_000,
                "used_units": 5_000_000,
                "remaining_units": 0,
                "period_start": 1_700_000_000,
                "period_end": 1_700_086_400,
            },
        ]
        windows, account, badge, note = _select_windows(
            {"plans": plans, "balances": balances}
        )
        self.assertEqual(account, "Start Plan")
        self.assertEqual(badge, "START")
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("1024 Dev Day", note)
        self.assertEqual(
            [window["title"] for window in windows],
            ["GLM-5.3", "GLM-5.3-Flash", "GLM-5.3", "GLM-5.3-Flash"],
        )
        self.assertEqual(
            [window["period_tag"] for window in windows],
            ["DAY", "DAY", "BONUS", "BONUS"],
        )
        self.assertEqual(windows[0]["remaining_percent"], 16.7)
        self.assertEqual(windows[1]["remaining_percent"], 0.0)
        self.assertEqual(windows[2]["remaining_percent"], 90.0)
        self.assertEqual(windows[3]["remaining_percent"], 93.3)
        self.assertEqual(windows[0]["unit"], "token")
        self.assertEqual(windows[0]["period_tag"], "DAY")
        self.assertEqual(windows[2]["period_tag"], "BONUS")

    def test_falls_back_to_one_time_windows(self) -> None:
        plans = [
            {
                "name": "ZCode Bonus",
                "plan_id": "bonus",
                "status": "active",
                "entitlements": [
                    {
                        "entitlement_id": "bonus",
                        "show_name": "GLM-5.3",
                        "period": "one_time",
                        "priority": 100,
                    }
                ],
            }
        ]
        balances = [
            {
                "entitlement_id": "bonus",
                "show_name": "GLM-5.3",
                "total_units": 100,
                "used_units": 25,
                "remaining_units": 75,
                "expires_at": 1_900_000_000,
            }
        ]
        windows, account, badge, _ = _select_windows({"plans": plans, "balances": balances})
        self.assertEqual(account, "Bonus")
        self.assertEqual(badge, "ZCODE")
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["period_tag"], "BONUS")

    def test_credential_decrypt(self) -> None:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            self.skipTest("cryptography is not installed")
        secret = "unit-test-secret"
        key = hashlib.sha256(secret.encode("utf-8")).digest()
        iv = bytes(range(12))
        payload = b"zcode-session"
        sealed = AESGCM(key).encrypt(iv, payload, None)
        ciphertext, tag = sealed[:-16], sealed[-16:]
        encoded = "enc:v1:" + ".".join(
            base64.urlsafe_b64encode(part).decode("ascii").rstrip("=")
            for part in (iv, tag, ciphertext)
        )
        with patch.dict(os.environ, {"ZCODE_CREDENTIAL_SECRET": secret}):
            self.assertEqual(decrypt_credential(encoded), "zcode-session")


class ResetTests(unittest.TestCase):
    def test_seeding_does_not_notify(self) -> None:
        state = {"windows": {}, "events": []}
        provider = {
            "id": "claude",
            "name": "Claude Code",
            "windows": [
                {"id": "five_hour", "title": "5 часов", "resets_at": 1_500, "period": "rolling_5h"}
            ],
        }
        events = _record_resets(state, [provider], 1_000, should_notify=False)
        self.assertEqual(events, [])
        self.assertEqual(state["seeded_at"], 1_000)
        self.assertIn("claude:five_hour", state["windows"])

    def test_new_window_creates_one_event_and_is_idempotent(self) -> None:
        state = {
            "seeded_at": 100,
            "windows": {
                "claude:five_hour": {
                    "resets_at": 990,
                    "title": "5 часов",
                    "provider_name": "Claude Code",
                    "updated_at": 900,
                }
            },
            "events": [],
        }
        provider = {
            "id": "claude",
            "name": "Claude Code",
            "windows": [
                {"id": "five_hour", "title": "5 часов", "resets_at": 2_000, "period": "rolling_5h"}
            ],
        }
        first = _record_resets(state, [provider], 1_000, should_notify=False)
        second = _record_resets(state, [provider], 1_001, should_notify=False)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["labels"], ["5 часов"])
        self.assertEqual(second, [])
        self.assertEqual(len(state["events"]), 1)

    def test_advancing_future_reset_does_not_notify(self) -> None:
        state = {
            "seeded_at": 100,
            "windows": {
                "codex:primary": {
                    "resets_at": 2_000,
                    "title": "5 часов",
                    "provider_name": "Codex",
                    "updated_at": 900,
                }
            },
            "events": [],
        }
        provider = {
            "id": "codex",
            "name": "Codex",
            "windows": [
                {"id": "primary", "title": "5 часов", "resets_at": 2_500, "period": "rolling_5h"}
            ],
        }
        events = _record_resets(state, [provider], 1_000, should_notify=False)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()

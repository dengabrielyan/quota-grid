from __future__ import annotations

import http.client
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from quota_manager import web

SNAPSHOT = {
    "schema_version": 1,
    "app_version": "1.1.0",
    "generated_at": 1_800_000_000,
    "next_refresh_at": 1_800_000_300,
    "interval_seconds": 300,
    "status": "ok",
    "providers": [
        {
            "id": "codex",
            "name": "Codex",
            "icon": "codex",
            "account": "ChatGPT Plus",
            "badge": "PLUS",
            "status": "ok",
            "error": None,
            "note": None,
            "windows": [
                {
                    "id": "primary",
                    "title": "5 часов",
                    "period_tag": "5H",
                    "period": "rolling_5h",
                    "used_percent": 42.0,
                    "remaining_percent": 58.0,
                    "resets_at": 1_800_010_000,
                    "unit": "percent",
                }
            ],
        }
    ],
    "recent_resets": [],
}


class WebServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = web.create_server(token="test-token")
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def request(self, path: str, *, headers: dict[str, str] | None = None, method: str = "GET"):
        request = urllib.request.Request(self.url(path), headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            body = error.read()
            headers = dict(error.headers)
            status = error.code
            error.close()
            return status, headers, body

    def test_index_and_assets_are_served(self) -> None:
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("quota-token", body.decode("utf-8"))
        self.assertIn("test-token", body.decode("utf-8"))
        self.assertIn("default-src", headers["Content-Security-Policy"])

        status, headers, _ = self.request("/assets/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers["Content-Type"])

        status, headers, _ = self.request("/assets/icons/claude.png")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")

    def test_status_requires_token_and_local_host(self) -> None:
        with patch.object(web, "status", return_value=SNAPSHOT):
            status, _, _ = self.request("/api/status")
            self.assertEqual(status, 403)

            status, headers, body = self.request(
                "/api/status", headers={"X-Quota-Token": "test-token"}
            )
            self.assertEqual(status, 200)
            self.assertIn("application/json", headers["Content-Type"])
            self.assertEqual(json.loads(body)["providers"][0]["id"], "codex")

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(
            "GET",
            "/api/status",
            headers={"Host": "evil.example", "X-Quota-Token": "test-token"},
        )
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 403)
        connection.close()

    def test_refresh_and_settings_endpoints(self) -> None:
        with patch.object(web, "refresh", return_value=SNAPSHOT) as refresh:
            status, _, body = self.request(
                "/api/refresh",
                headers={"X-Quota-Token": "test-token"},
                method="POST",
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["status"], "ok")
            refresh.assert_called_once_with(notify=False)

        status, _, _ = self.request("/api/refresh", method="POST")
        self.assertEqual(status, 403)

        with patch.object(web, "open_settings_file", return_value=(0, "/tmp/config.json")):
            status, _, body = self.request(
                "/api/settings",
                headers={"X-Quota-Token": "test-token"},
                method="POST",
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"ok": True, "path": "/tmp/config.json"})

    def test_unknown_path_is_not_found(self) -> None:
        status, _, _ = self.request("/assets/../../etc/passwd")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

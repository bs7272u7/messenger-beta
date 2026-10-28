import unittest
from unittest.mock import MagicMock, patch

import requests

import app as app_module


def github_response(sha="abcdef1234567", message="첫 줄\n둘째 줄"):
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.links = {}
    response.json.return_value = [
        {"sha": sha, "commit": {"author": {"date": "2026-10-28T00:00:00Z"}, "message": message}}
    ]
    return response


class UpdateHistoryTest(unittest.TestCase):
    def setUp(self):
        for cache in app_module._update_history_cache.values():
            cache.update({"expires_at": 0, "retry_at": 0, "data": None})

    def expire(self):
        cache = app_module._update_history_cache["recent"]
        cache["expires_at"] = 0
        cache["retry_at"] = 0

    def test_success_is_cached(self):
        with patch.object(app_module.requests, "get", return_value=github_response()) as get:
            first = app_module.get_update_history()
            second = app_module.get_update_history()
        self.assertEqual(first["updates"][0]["message"], "첫 줄")
        self.assertEqual(first["latest_version"], "abcdef1")
        self.assertEqual(second, first)
        self.assertEqual(get.call_count, 1)

    def test_failure_returns_stale_data(self):
        with patch.object(app_module.requests, "get", return_value=github_response()):
            good = app_module.get_update_history()
        self.expire()
        with patch.object(app_module.requests, "get", side_effect=requests.ConnectionError()):
            self.assertEqual(app_module.get_update_history(), good)

    def test_failure_without_data_returns_none(self):
        with patch.object(app_module.requests, "get", side_effect=requests.ConnectionError()):
            self.assertIsNone(app_module.get_update_history())

    def test_failure_backs_off(self):
        with patch.object(
            app_module.requests, "get", side_effect=requests.ConnectionError()
        ) as get:
            app_module.get_update_history()
            app_module.get_update_history()
        self.assertEqual(get.call_count, 1)

    def test_rate_limit_status_is_logged(self):
        limited = MagicMock()
        limited.status_code = 403
        limited.headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "123"}
        limited.raise_for_status.side_effect = requests.HTTPError()
        with patch.object(app_module.requests, "get", return_value=limited):
            with self.assertLogs(app_module.app.logger, "WARNING") as logs:
                app_module.get_update_history()
        self.assertIn("status=403", logs.output[0])
        self.assertIn("remaining=0", logs.output[0])


if __name__ == "__main__":
    unittest.main()

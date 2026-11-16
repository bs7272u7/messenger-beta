import unittest
from unittest.mock import patch

import psycopg2

import app as app_module


class DatabaseUnavailableTest(unittest.TestCase):
    """DB에 연결할 수 없으면 일반 서버 오류(500) 대신 503과 DB 안내 문구를 돌려준다."""

    def test_login_reports_database_unavailable(self):
        client = app_module.app.test_client()
        with client.session_transaction() as session:
            session["csrf_token"] = "csrf"
        with patch.object(
            app_module.user_repository,
            "find_for_login",
            side_effect=psycopg2.OperationalError("could not connect to server"),
        ):
            response = client.post(
                "/api/login",
                json={"identifier": "someone", "password": "pw"},
                headers={"X-CSRF-Token": "csrf"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("데이터베이스에 연결할 수 없습니다", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()

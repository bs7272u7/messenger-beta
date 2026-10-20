"""UserRepository.find_for_login 단위 테스트. 실행된 SQL과 파라미터를 가짜 연결로 기록해 확인한다."""

import unittest

from repositories.user_repository import UserRepository


class FakeCursor:
    """fetchone만 흉내 내는 커서."""

    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConnection:
    """컨텍스트 매니저로 쓰이는 가짜 DB 연결. 마지막으로 실행된 query와 params를 보관한다."""

    def __init__(self, row):
        self._row = row
        self.query = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params
        return FakeCursor(self._row)


class UserRepositoryTest(unittest.TestCase):
    """로그인 식별자가 이메일이면 소문자로 바꿔 email 컬럼을, 아니면 username 컬럼을 조회해야 한다."""

    def test_email_login_uses_lowercase_email(self):
        connection = FakeConnection({"id": 1, "username": "tester"})
        repository = UserRepository(lambda: connection)

        result = repository.find_for_login("USER@EXAMPLE.COM")

        self.assertEqual(result["id"], 1)
        self.assertIn("WHERE email = %s", connection.query)
        self.assertEqual(connection.params, ("user@example.com",))

    def test_username_login_keeps_username_query(self):
        connection = FakeConnection({"id": 1, "username": "tester"})
        repository = UserRepository(lambda: connection)

        result = repository.find_for_login("tester")

        self.assertEqual(result["username"], "tester")
        self.assertIn("WHERE username = %s", connection.query)
        self.assertEqual(connection.params, ("tester",))

    def test_missing_user_returns_none(self):
        connection = FakeConnection(None)
        repository = UserRepository(lambda: connection)

        result = repository.find_for_login("missing-user")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

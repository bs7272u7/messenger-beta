import unittest

from repositories.user_repository import UserRepository


class FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConnection:
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

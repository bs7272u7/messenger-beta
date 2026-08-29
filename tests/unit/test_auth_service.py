import unittest

from werkzeug.security import generate_password_hash

from services.auth_service import AuthService


class FakeUserRepository:
    def __init__(self, user):
        self.user = user

    def find_for_login(self, identifier):
        return self.user


class AuthServiceTest(unittest.TestCase):
    def test_valid_password_returns_user(self):
        user = {
            "id": 1,
            "username": "tester",
            "password_hash": generate_password_hash("password!1"),
        }
        service = AuthService(FakeUserRepository(user))

        result = service.authenticate("tester", "password!1")

        self.assertEqual(result["id"], 1)

    def test_invalid_password_returns_none(self):
        user = {
            "id": 1,
            "password_hash": generate_password_hash("password!1"),
        }
        service = AuthService(FakeUserRepository(user))

        result = service.authenticate("tester", "wrong-password")

        self.assertIsNone(result)

    def test_unknown_user_returns_none(self):
        service = AuthService(FakeUserRepository(None))

        result = service.authenticate("missing-user", "password!1")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

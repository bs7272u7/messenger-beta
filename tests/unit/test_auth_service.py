"""AuthService.authenticate 단위 테스트. 저장소를 가짜(FakeUserRepository)로 바꿔 비밀번호 해시 검증만 확인한다."""

import unittest

from werkzeug.security import generate_password_hash

from services.auth_service import AuthService


class FakeUserRepository:
    """find_for_login이 항상 같은 사용자(또는 None)를 돌려주는 테스트용 저장소."""

    def __init__(self, user):
        self.user = user

    def find_for_login(self, identifier):
        return self.user


class AuthServiceTest(unittest.TestCase):
    """올바른 비밀번호는 사용자를, 틀린 비밀번호나 없는 사용자는 None을 돌려줘야 한다."""

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

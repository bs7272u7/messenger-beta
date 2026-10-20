"""RegistrationService.register 단위 테스트. 이메일 인증번호 확인과 계정 생성 흐름을 가짜 연결로 검증한다."""

import unittest

from services.registration_service import RegistrationError, RegistrationService


class FakeResult:
    """fetchone만 흉내 내는 쿼리 결과."""

    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConnection:
    """인증번호 행(verification)을 돌려주고, 실행된 쿼리를 기록하며 commit 여부를 보관하는 가짜 연결. 아이디·이메일 중복은 없는 것으로, INSERT는 id 42를 돌려주는 것으로 응답한다."""

    def __init__(self, verification):
        self.verification = verification
        self.committed = False
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if "email_verification_codes WHERE email" in query:
            return FakeResult(self.verification)
        if "SELECT id FROM users" in query:
            return FakeResult()
        if "INSERT INTO users" in query:
            return FakeResult({"id": 42})
        return FakeResult()

    def commit(self):
        self.committed = True


class RegistrationServiceTests(unittest.TestCase):
    """유효한 인증번호로는 계정이 만들어지고, 만료된 인증번호는 거부되어야 한다."""

    def setUp(self):
        """현재 시각을 2026-08-26 21:00:00으로 고정하고, 인증번호 만료 시각을 그보다 뒤(23:59:59)로 둔다."""
        self.connection = FakeConnection({"expires_at": "2026-08-26 23:59:59"})
        self.service = RegistrationService(
            lambda: self.connection,
            lambda: "2026-08-26 21:00:00",
            "/static/default_profile.png",
            "admin@example.com",
        )

    def test_register_creates_a_verified_account(self):
        """인증번호가 유효하면 계정을 만들고 commit한다."""
        result = self.service.register(
            username="newuser",
            email="new@example.com",
            password="cloud!7",
            display_name="",
            language="ko",
            code="123456",
        )

        self.assertEqual(result.id, 42)
        self.assertEqual(result.display_name, "newuser")
        self.assertTrue(self.connection.committed)

    def test_register_rejects_expired_verification_code(self):
        """만료 시각이 현재보다 1초라도 이르면 '만료' 오류로 거부한다."""
        self.connection.verification = {"expires_at": "2026-08-26 20:59:59"}

        with self.assertRaisesRegex(RegistrationError, "만료"):
            self.service.register(
                username="newuser",
                email="new@example.com",
                password="cloud!7",
                display_name="New user",
                language="ko",
                code="123456",
            )


if __name__ == "__main__":
    unittest.main()

import unittest

from services.registration_service import RegistrationError, RegistrationService


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class FakeConnection:
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
    def setUp(self):
        self.connection = FakeConnection({"expires_at": "2026-08-26 23:59:59"})
        self.service = RegistrationService(
            lambda: self.connection,
            lambda: "2026-08-26 21:00:00",
            "/static/default_profile.png",
            "admin@example.com",
        )

    def test_register_creates_a_verified_account(self):
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

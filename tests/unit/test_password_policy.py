import unittest

from services.password_policy import PasswordPolicy


class PasswordPolicyTests(unittest.TestCase):
    def test_accepts_password_with_all_required_character_types(self):
        self.assertTrue(PasswordPolicy.is_valid("cloud!7"))

    def test_rejects_password_missing_a_required_character_type(self):
        for password in ("cloud77", "CLOUD!7", "clouding", "cl0ud77"):
            with self.subTest(password=password):
                self.assertFalse(PasswordPolicy.is_valid(password))

    def test_rejects_password_shorter_than_seven_characters(self):
        self.assertFalse(PasswordPolicy.is_valid("cl!7a"))


if __name__ == "__main__":
    unittest.main()

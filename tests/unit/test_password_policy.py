"""비밀번호 정책(PasswordPolicy) 단위 테스트."""

import unittest

from services.password_policy import PasswordPolicy


class PasswordPolicyTests(unittest.TestCase):
    """정책: 7자 이상이며 영문 소문자·숫자·특수문자를 각각 하나 이상 포함해야 한다."""

    def test_accepts_password_with_all_required_character_types(self):
        self.assertTrue(PasswordPolicy.is_valid("cloud!7"))

    def test_rejects_password_missing_a_required_character_type(self):
        # 특수문자 없음 / 소문자 없음 / 숫자·특수문자 없음 / 특수문자 없음(0이 섞인 경우) 등 조건 하나씩이 빠진 비밀번호를 확인한다.
        for password in ("cloud77", "CLOUD!7", "clouding", "cl0ud77"):
            with self.subTest(password=password):
                self.assertFalse(PasswordPolicy.is_valid(password))

    def test_rejects_password_shorter_than_seven_characters(self):
        self.assertFalse(PasswordPolicy.is_valid("cl!7a"))


if __name__ == "__main__":
    unittest.main()

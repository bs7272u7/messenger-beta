"""User 모델(DB 행 → 로그인 사용자 객체) 단위 테스트."""

import unittest

from models.user import User


class UserModelTest(unittest.TestCase):
    """표시 이름과 기본값 처리를 확인한다."""

    def make_row(self, **overrides):
        """테스트용 users 행을 만든다. overrides로 필요한 컬럼만 바꾼다."""
        row = {
            "id": 1,
            "username": "tester",
            "display_name": "테스터",
            "email": "tester@example.com",
            "is_admin": False,
            "profile_visibility": "friends",
            "is_suspended": False,
            "suspended_until": 0,
            "language": "ko",
            "created_at": "2026-08-26 12:00:00",
        }
        row.update(overrides)
        return row

    def test_display_name_is_used_when_present(self):
        """표시 이름이 있으면 그것을 name으로 쓰고, Flask-Login의 get_id()는 문자열 ID를 돌려준다."""
        user = User.from_row(self.make_row(display_name="재현"))

        self.assertEqual(user.name, "재현")
        self.assertEqual(user.get_id(), "1")

    def test_username_is_used_when_display_name_is_missing(self):
        """표시 이름이 없으면 아이디를 쓰고, 비어 있는 언어·공개 범위는 기본값(ko, friends)으로 채운다."""
        user = User.from_row(
            self.make_row(
                display_name=None,
                language=None,
                profile_visibility=None,
            )
        )

        self.assertEqual(user.name, "tester")
        self.assertEqual(user.language, "ko")
        self.assertEqual(user.profile_visibility, "friends")


if __name__ == "__main__":
    unittest.main()

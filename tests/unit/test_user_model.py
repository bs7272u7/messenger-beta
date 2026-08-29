import unittest

from models.user import User


class UserModelTest(unittest.TestCase):
    def make_row(self, **overrides):
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
            "chess_rating": 400,
            "chess_wins": 0,
            "chess_draws": 0,
            "chess_losses": 0,
            "created_at": "2026-08-26 12:00:00",
        }
        row.update(overrides)
        return row

    def test_display_name_is_used_when_present(self):
        user = User.from_row(self.make_row(display_name="재현"))

        self.assertEqual(user.name, "재현")
        self.assertEqual(user.get_id(), "1")

    def test_username_is_used_when_display_name_is_missing(self):
        user = User.from_row(
            self.make_row(
                display_name=None,
                language=None,
                profile_visibility=None,
                chess_rating=None,
            )
        )

        self.assertEqual(user.name, "tester")
        self.assertEqual(user.language, "ko")
        self.assertEqual(user.profile_visibility, "friends")
        self.assertEqual(user.chess_rating, 400)


if __name__ == "__main__":
    unittest.main()

import unittest

from services.friend_service import FriendService, FriendServiceError


class FriendServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = FriendService(
            lambda: self.fail("DB 연결이 호출되면 안 됩니다."),
            lambda: "2026-08-26 21:00:00",
            lambda *_: False,
            lambda *_: None,
        )

    def test_send_request_requires_a_username(self):
        with self.assertRaisesRegex(FriendServiceError, "아이디"):
            self.service.send_request(1, "sender", "")

    def test_block_rejects_self(self):
        with self.assertRaisesRegex(FriendServiceError, "자기 자신"):
            self.service.block(1, 1)


if __name__ == "__main__":
    unittest.main()

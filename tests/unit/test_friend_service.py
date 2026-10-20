"""FriendService 단위 테스트. DB를 쓰지 않는 입력 검증 경로만 확인한다."""

import unittest

from services.friend_service import FriendService, FriendServiceError


class FriendServiceTests(unittest.TestCase):
    """입력 검증은 DB에 접근하기 전에 끝나야 한다. setUp의 연결 팩토리는 호출되면 즉시 실패해 그 점을 보장한다."""

    def setUp(self):
        """연결 팩토리가 호출되면 테스트가 실패하도록 해서, 검증 단계에서 DB를 건드리지 않음을 확인한다."""
        self.service = FriendService(
            lambda: self.fail("DB 연결이 호출되면 안 됩니다."),
            lambda: "2026-08-26 21:00:00",
            lambda *_: False,
            lambda *_: None,
        )

    def test_send_request_requires_a_username(self):
        """빈 아이디로 친구 요청을 보내면 DB 조회 없이 거부한다."""
        with self.assertRaisesRegex(FriendServiceError, "아이디"):
            self.service.send_request(1, "sender", "")

    def test_block_rejects_self(self):
        """자기 자신은 차단할 수 없다."""
        with self.assertRaisesRegex(FriendServiceError, "자기 자신"):
            self.service.block(1, 1)


if __name__ == "__main__":
    unittest.main()

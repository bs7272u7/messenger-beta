"""메시지 요청 규칙(send_block_reason)과 DmRequestService 입력 검증 테스트."""

import unittest

from services.dm_request_service import (
    DECLINED_MESSAGE_LIMIT,
    PENDING_MESSAGE_LIMIT,
    DmRequestError,
    DmRequestService,
    send_block_reason,
)


class FakeConn:
    """send_block_reason이 하는 두 가지 조회(대화방 상태, 보낸 메시지 수)에 정해 둔 값을 돌려주는 가짜 연결."""

    def __init__(self, conversation, sent=0):
        self.conversation = conversation
        self.sent = sent

    def execute(self, sql, params=()):
        class Result:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row

        if "FROM conversations" in sql:
            return Result(self.conversation)
        return Result({"n": self.sent})


def conv(state, requester=1):
    return {"dm_state": state, "dm_requester_id": requester}


class SendBlockReasonTests(unittest.TestCase):
    """수락 대기·거절된 방에서 누가 얼마나 보낼 수 있는지 확인한다."""

    def test_active_and_missing_rooms_are_unrestricted(self):
        """보통 방(그룹 포함)과 없는 방은 이 규칙이 막지 않는다."""
        self.assertIsNone(send_block_reason(FakeConn(conv("active", None)), 1, 2))
        self.assertIsNone(send_block_reason(FakeConn(None), 1, 2))

    def test_recipient_cannot_reply_before_accepting(self):
        """받는 사람은 수락 전에는 답장할 수 없다."""
        reason = send_block_reason(FakeConn(conv("pending", requester=1)), 9, 2)
        self.assertEqual(reason[0], 403)
        self.assertIn("수락", reason[1])

    def test_recipient_cannot_reply_after_declining(self):
        """거절한 대화에도 답장할 수 없다."""
        reason = send_block_reason(FakeConn(conv("declined", requester=1)), 9, 2)
        self.assertIn("거절", reason[1])

    def test_requester_is_capped_while_pending(self):
        """보낸 사람은 수락 전에 정해진 개수까지만 보낼 수 있다."""
        self.assertIsNone(
            send_block_reason(FakeConn(conv("pending"), sent=PENDING_MESSAGE_LIMIT - 1), 9, 1)
        )
        self.assertIsNotNone(
            send_block_reason(FakeConn(conv("pending"), sent=PENDING_MESSAGE_LIMIT), 9, 1)
        )

    def test_requester_has_a_larger_cap_after_decline(self):
        """거절된 뒤에는 보낸 사람이 더 많이(누적 상한까지) 보낼 수 있다."""
        self.assertIsNone(
            send_block_reason(FakeConn(conv("declined"), sent=DECLINED_MESSAGE_LIMIT - 1), 9, 1)
        )
        self.assertIsNotNone(
            send_block_reason(FakeConn(conv("declined"), sent=DECLINED_MESSAGE_LIMIT), 9, 1)
        )


class DmRequestServiceTests(unittest.TestCase):
    """입력 검증은 DB 접근 전에 끝나야 한다."""

    def setUp(self):
        """연결 팩토리가 호출되면 테스트가 실패하게 해서 검증 단계의 DB 접근을 막는다."""
        self.service = DmRequestService(
            lambda: self.fail("DB 연결이 호출되면 안 됩니다."),
            lambda: "2026-10-26 12:00:00",
            lambda *_: False,
            lambda *_: False,
        )

    def test_start_conversation_rejects_self(self):
        """자기 자신과는 대화를 시작할 수 없다."""
        with self.assertRaisesRegex(DmRequestError, "자기 자신"):
            self.service.start_conversation(1, 1)

    def test_start_conversation_rejects_non_integer_target(self):
        """대상 ID가 정수가 아니면 거부한다."""
        for bad in ("2", None, True):
            with self.assertRaises(DmRequestError):
                self.service.start_conversation(1, bad)


if __name__ == "__main__":
    unittest.main()

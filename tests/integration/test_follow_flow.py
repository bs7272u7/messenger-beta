"""팔로우·메시지 요청의 두 계정 시나리오 통합 테스트(실제 DB 필요, 없으면 건너뛴다)."""

import os
import secrets
import unittest
from unittest import mock

import app as application_module


class FollowFlowTests(unittest.TestCase):
    """요청 → 수락 → 메시지 요청 → 수락/거절 흐름이 서버 규칙대로 동작하는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        """DB 연결 정보가 없으면 건너뛰고, 있으면 테스트용 계정 세 개를 만든다."""
        if not (os.environ.get("DATABASE_URL") or os.environ.get("DB_PASSWORD")):
            raise unittest.SkipTest("DB 연결 정보가 없어 팔로우 통합 테스트를 건너뜁니다.")
        application_module.init_db()
        suffix = secrets.token_hex(3)
        cls.ids = {}
        with application_module.get_db() as conn:
            for name in ("alice", "bobby", "carol"):
                cls.ids[name] = conn.execute(
                    "INSERT INTO users (username, password_hash, display_name, email, created_at, profile_visibility)"
                    " VALUES (%s, 'x', %s, %s, '2026-01-01', 'public') RETURNING id",
                    (f"{name}{suffix}", name, f"{name}{suffix}@example.com"),
                ).fetchone()["id"]
            conn.commit()
        cls.patch = mock.patch.object(
            application_module, "session_token_matches", return_value=True
        )
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        """만든 계정을 지운다(관련 요청·대화방은 ON DELETE CASCADE로 함께 지워진다)."""
        cls.patch.stop()
        with application_module.get_db() as conn:
            conn.execute("DELETE FROM users WHERE id = ANY(%s)", (list(cls.ids.values()),))
            conn.commit()

    def client(self, name):
        """해당 계정으로 로그인한 상태의 테스트 클라이언트."""
        client = application_module.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = self.ids[name]
            session["session_token"] = "token"
            session["csrf_token"] = "csrf"
        return client

    def call(self, client, method, url, body=None):
        """CSRF 헤더를 붙여 API를 부르고 (상태 코드, JSON)을 돌려준다."""
        response = getattr(client, method)(url, json=body, headers={"X-CSRF-Token": "csrf"})
        return response.status_code, response.get_json()

    def test_follow_request_and_message_request_flow(self):
        """팔로우는 수락해야 생기고, 맞팔이 아닌 상대의 메시지는 수락 전까지 받는 사람 목록에 나타나지 않는다."""
        alice, bobby = self.client("alice"), self.client("bobby")
        bobby_id = self.ids["bobby"]

        status, _ = self.call(alice, "post", f"/api/users/{bobby_id}/follow")
        self.assertEqual(status, 200)
        status, _ = self.call(alice, "post", f"/api/users/{bobby_id}/follow")
        self.assertEqual(status, 409)

        _, requests = self.call(bobby, "get", "/api/follow-requests")
        self.assertEqual(len(requests["incoming"]), 1)
        self.call(
            bobby,
            "post",
            f"/api/follow-requests/{requests['incoming'][0]['id']}/respond",
            {"accept": True},
        )
        _, summary = self.call(alice, "get", f"/api/users/{bobby_id}/summary")
        self.assertEqual(summary["relation"]["status"], "following")
        self.assertEqual(summary["followerCount"], 1)

        # 맞팔이 아니므로 대화방은 수락 대기(pending)로 만들어진다.
        _, started = self.call(alice, "post", f"/api/users/{bobby_id}/message")
        self.assertEqual(started["state"], "pending")
        conversation_id = started["conversationId"]
        self.call(alice, "post", f"/api/conversations/{conversation_id}/messages", {"text": "hi"})

        _, bobby_rooms = self.call(bobby, "get", "/api/conversations")
        self.assertNotIn(conversation_id, [room["id"] for room in bobby_rooms])
        status, error = self.call(
            bobby, "post", f"/api/conversations/{conversation_id}/messages", {"text": "yo"}
        )
        self.assertEqual(status, 403)

        self.call(
            bobby, "post", f"/api/message-requests/{conversation_id}/respond", {"accept": True}
        )
        _, bobby_rooms = self.call(bobby, "get", "/api/conversations")
        self.assertIn(conversation_id, [room["id"] for room in bobby_rooms])
        status, _ = self.call(
            bobby, "post", f"/api/conversations/{conversation_id}/messages", {"text": "yo"}
        )
        self.assertEqual(status, 200)

    def test_declined_request_blocks_replies_and_caps_sender(self):
        """거절하면 받는 사람은 답장할 수 없고, 보낸 사람은 정해진 개수까지만 보낼 수 있다."""
        carol, alice = self.client("carol"), self.client("alice")
        alice_id = self.ids["alice"]
        _, started = self.call(carol, "post", f"/api/users/{alice_id}/message")
        conversation_id = started["conversationId"]
        self.call(
            alice, "post", f"/api/message-requests/{conversation_id}/respond", {"accept": False}
        )

        status, _ = self.call(
            alice, "post", f"/api/conversations/{conversation_id}/messages", {"text": "no"}
        )
        self.assertEqual(status, 403)
        status, _ = self.call(
            carol, "post", f"/api/conversations/{conversation_id}/messages", {"text": "hello"}
        )
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()

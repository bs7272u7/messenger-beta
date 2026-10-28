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
        self.assertGreaterEqual(summary["followerCount"], 1)

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

    def test_same_pair_never_gets_two_one_on_one_rooms(self):
        """메시지를 먼저 보낸 뒤 친구가 되어도, 두 사람 사이의 1:1 대화방은 하나만 있어야 한다."""
        alice, bobby = self.client("alice"), self.client("bobby")
        bobby_id, alice_id = self.ids["bobby"], self.ids["alice"]
        # 이전 테스트가 만든 방이 있어도 같은 방을 돌려줘야 하므로 두 번 시작해 본다.
        _, first = self.call(alice, "post", f"/api/users/{bobby_id}/message")
        _, second = self.call(alice, "post", f"/api/users/{bobby_id}/message")
        self.assertEqual(first["conversationId"], second["conversationId"])

        self.call(alice, "post", "/api/friend-requests", {"username": self._username("bobby")})
        _, requests = self.call(bobby, "get", "/api/friend-requests")
        incoming = [r for r in requests["incoming"] if r["user_id"] == alice_id]
        self.call(
            bobby, "post", f"/api/friend-requests/{incoming[0]['id']}/respond", {"accept": True}
        )

        with application_module.get_db() as conn:
            rooms = conn.execute(
                "SELECT COUNT(DISTINCT c.id) AS n FROM conversations c"
                " JOIN conversation_members a ON a.conversation_id = c.id AND a.user_id = %s"
                " JOIN conversation_members b ON b.conversation_id = c.id AND b.user_id = %s"
                " WHERE NOT c.is_group",
                (alice_id, bobby_id),
            ).fetchone()["n"]
        self.assertEqual(rooms, 1)

    def test_deleted_room_comes_back_without_old_messages(self):
        """대화방을 삭제(숨김)하면 그때까지의 메시지는 내게서 지워지고, 이후 새 메시지로 방이 다시 나타나도 새 메시지만 보인다."""
        bobby, carol = self.client("bobby"), self.client("carol")
        carol_id = self.ids["carol"]
        # 다른 테스트가 쓰지 않은 쌍(bobby·carol)으로 확인한다. 맞팔이 아니면 수락 대기 방이 되므로, 서로 팔로우해 바로 쓰는 방(active)으로 만든다.
        with application_module.get_db() as conn:
            for follower, followee in (
                (self.ids["bobby"], carol_id),
                (carol_id, self.ids["bobby"]),
            ):
                conn.execute(
                    "INSERT INTO follows (follower_id, followee_id, created_at) VALUES (%s, %s, 'x')"
                    " ON CONFLICT DO NOTHING",
                    (follower, followee),
                )
            conn.commit()
        _, started = self.call(bobby, "post", f"/api/users/{carol_id}/message")
        self.assertEqual(started["state"], "active")
        conversation_id = started["conversationId"]
        self.call(bobby, "post", f"/api/conversations/{conversation_id}/messages", {"text": "old"})

        self.call(bobby, "post", f"/api/conversations/{conversation_id}/hide")
        _, rooms = self.call(bobby, "get", "/api/conversations")
        self.assertNotIn(conversation_id, [room["id"] for room in rooms])

        self.call(carol, "post", f"/api/conversations/{conversation_id}/messages", {"text": "new"})
        _, rooms = self.call(bobby, "get", "/api/conversations")
        room = next(room for room in rooms if room["id"] == conversation_id)
        self.assertEqual(room["message"], "new")
        _, messages = self.call(bobby, "get", f"/api/conversations/{conversation_id}/messages")
        self.assertEqual([m["text"] for m in messages], ["new"])
        # 상대(carol)의 기록은 그대로다.
        _, theirs = self.call(carol, "get", f"/api/conversations/{conversation_id}/messages")
        self.assertEqual([m["text"] for m in theirs], ["old", "new"])

    def _username(self, name):
        """테스트 계정의 아이디."""
        with application_module.get_db() as conn:
            return conn.execute(
                "SELECT username FROM users WHERE id = %s", (self.ids[name],)
            ).fetchone()["username"]


if __name__ == "__main__":
    unittest.main()

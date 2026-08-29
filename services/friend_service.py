"""친구 요청의 상태 전이와 1:1 대화방 생성을 관리한다."""

from __future__ import annotations

from dataclasses import dataclass


class FriendServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FriendRequestOutcome:
    notify_user_id: int
    auto_accepted: bool = False


class FriendService:
    def __init__(self, connection_factory, now_string, blocked_either_way, accept_request) -> None:
        self._connection_factory = connection_factory
        self._now_string = now_string
        self._blocked_either_way = blocked_either_way
        self._accept_request = accept_request

    def send_request(self, requester_id: int, requester_username: str, target_username: str):
        if not target_username:
            raise FriendServiceError("아이디를 입력해주세요.")
        if target_username == requester_username:
            raise FriendServiceError("자기 자신에게는 요청할 수 없습니다.")

        with self._connection_factory() as conn:
            target = conn.execute(
                "SELECT id FROM users WHERE username = %s", (target_username,)
            ).fetchone()
            if not target:
                raise FriendServiceError("존재하지 않는 아이디입니다.")
            target_id = target["id"]
            if self._blocked_either_way(conn, requester_id, target_id):
                raise FriendServiceError("차단 관계에서는 친구 요청을 보낼 수 없습니다.")
            # 채팅방 존재 여부와 친구 관계는 별개다. 숨긴 과거 대화방이 있어도
            # 친구 삭제 후 다시 요청할 수 있어야 하므로 수락된 요청만 확인한다.
            if conn.execute(
                """
                SELECT id FROM friend_requests
                WHERE status = 'accepted'
                  AND ((requester_id = %s AND addressee_id = %s)
                    OR (requester_id = %s AND addressee_id = %s))
                """,
                (requester_id, target_id, target_id, requester_id),
            ).fetchone():
                raise FriendServiceError("이미 친구입니다.")
            reverse = conn.execute(
                "SELECT id FROM friend_requests WHERE requester_id = %s AND addressee_id = %s AND status = 'pending'",
                (target_id, requester_id),
            ).fetchone()
            if reverse:
                self._accept_request(conn, reverse["id"])
                conn.commit()
                return FriendRequestOutcome(target_id, auto_accepted=True)
            existing = conn.execute(
                "SELECT id, status FROM friend_requests WHERE requester_id = %s AND addressee_id = %s",
                (requester_id, target_id),
            ).fetchone()
            if existing and existing["status"] == "pending":
                raise FriendServiceError("이미 요청을 보냈습니다.")
            if existing:
                conn.execute(
                    "UPDATE friend_requests SET status = 'pending', created_at = %s WHERE id = %s",
                    (self._now_string(), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO friend_requests (requester_id, addressee_id, status, created_at) VALUES (%s, %s, 'pending', %s)",
                    (requester_id, target_id, self._now_string()),
                )
            conn.commit()
        return FriendRequestOutcome(target_id)

    def respond(self, request_id: int, user_id: int, accepted: bool) -> int:
        with self._connection_factory() as conn:
            request_row = conn.execute(
                "SELECT * FROM friend_requests WHERE id = %s AND addressee_id = %s AND status = 'pending'",
                (request_id, user_id),
            ).fetchone()
            if not request_row:
                raise FriendServiceError("요청을 찾을 수 없습니다.", 404)
            if accepted:
                self._accept_request(conn, request_id)
            else:
                conn.execute(
                    "UPDATE friend_requests SET status = 'declined' WHERE id = %s", (request_id,)
                )
            conn.commit()
        return request_row["requester_id"]

    def cancel(self, request_id: int, user_id: int) -> int:
        with self._connection_factory() as conn:
            request_row = conn.execute(
                "SELECT id, addressee_id FROM friend_requests WHERE id = %s AND requester_id = %s AND status = 'pending'",
                (request_id, user_id),
            ).fetchone()
            if not request_row:
                raise FriendServiceError("취소할 친구 요청을 찾을 수 없습니다.", 404)
            conn.execute("DELETE FROM friend_requests WHERE id = %s", (request_id,))
            conn.commit()
        return request_row["addressee_id"]

    def list_friends(self, user_id: int) -> list[dict]:
        """숨긴 채팅방과 무관하게 실제 수락된 친구 관계를 반환한다."""
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT peer.id, peer.username, peer.display_name, peer.profile_image,
                       EXISTS(
                           SELECT 1 FROM blocks
                           WHERE blocker_id = %s AND blocked_id = peer.id
                       ) AS blocked_by_me,
                       EXISTS(
                           SELECT 1 FROM blocks
                           WHERE blocker_id = peer.id AND blocked_id = %s
                       ) AS blocked_me
                FROM friend_requests request
                JOIN users peer ON peer.id = CASE
                    WHEN request.requester_id = %s THEN request.addressee_id
                    ELSE request.requester_id
                END
                WHERE request.status = 'accepted'
                  AND (request.requester_id = %s OR request.addressee_id = %s)
                ORDER BY COALESCE(peer.display_name, peer.username), peer.username
                """,
                (user_id, user_id, user_id, user_id, user_id),
            ).fetchall()
        return [
            {
                "peerId": row["id"],
                "peerUsername": row["username"],
                "name": row["display_name"] or row["username"],
                "peerProfileImage": row["profile_image"],
                "blockedByMe": bool(row["blocked_by_me"]),
                "blockedMe": bool(row["blocked_me"]),
            }
            for row in rows
        ]

    def remove_friend(self, user_id: int, target_id: int) -> int:
        """친구 관계만 해제한다. 채팅방 숨김·삭제와는 별개의 동작이다."""
        with self._connection_factory() as conn:
            request_row = conn.execute(
                """
                SELECT id FROM friend_requests
                WHERE status = 'accepted'
                  AND ((requester_id = %s AND addressee_id = %s)
                    OR (requester_id = %s AND addressee_id = %s))
                """,
                (user_id, target_id, target_id, user_id),
            ).fetchone()
            if not request_row:
                raise FriendServiceError("친구 관계를 찾을 수 없습니다.", 404)
            conn.execute("DELETE FROM friend_requests WHERE id = %s", (request_row["id"],))
            conn.commit()
        return target_id

    def list_blocks(self, user_id: int) -> list[dict]:
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT users.id, users.display_name, users.username FROM blocks JOIN users ON users.id = blocks.blocked_id WHERE blocks.blocker_id = %s ORDER BY blocks.created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def block(self, user_id: int, target_id: int | None) -> int:
        if not target_id:
            raise FriendServiceError("차단할 대상을 지정해주세요.", 400)
        if target_id == user_id:
            raise FriendServiceError("자기 자신은 차단할 수 없습니다.", 400)
        with self._connection_factory() as conn:
            if not conn.execute("SELECT id FROM users WHERE id = %s", (target_id,)).fetchone():
                raise FriendServiceError("사용자를 찾을 수 없습니다.", 404)
            if not conn.execute(
                "SELECT id FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
                (user_id, target_id),
            ).fetchone():
                conn.execute(
                    "INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (%s, %s, %s)",
                    (user_id, target_id, self._now_string()),
                )
                conn.commit()
        return target_id

    def unblock(self, user_id: int, target_id: int) -> None:
        with self._connection_factory() as conn:
            conn.execute(
                "DELETE FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
                (user_id, target_id),
            )
            conn.commit()

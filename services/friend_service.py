"""친구 요청, 친구 관계, 차단, 1:1 대화방 복원을 관리하는 서비스.

친구 관계(friend_requests)와 대화방 표시 상태(숨김 등)는 서로 독립이다.
한쪽을 바꿔도 다른 쪽이 따라 바뀌지 않도록 각 메서드가 자기 테이블만 다룬다.
"""

from __future__ import annotations

from dataclasses import dataclass


class FriendServiceError(Exception):
    """친구 기능의 예상 가능한 검증 오류. HTTP 상태 코드를 함께 담아 블루프린트가 그대로 응답에 쓴다."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FriendRequestOutcome:
    """친구 요청 처리 결과.

    Attributes:
        notify_user_id: 실시간 알림을 보낼 상대 사용자 ID.
        auto_accepted: 상대가 먼저 보낸 요청이 있어 자동으로 수락됐는지 여부.
    """

    notify_user_id: int
    auto_accepted: bool = False


class FriendService:
    """친구 요청 상태와 차단 관계를 채팅방 표시 상태와 분리해 관리한다."""

    def __init__(self, connection_factory, now_string, blocked_either_way, accept_request) -> None:
        """서비스가 쓸 DB 연결과 보조 함수를 주입받는다.

        Args:
            connection_factory: DB 연결을 만들어 주는 함수.
            now_string: 현재 시각 문자열을 돌려주는 함수.
            blocked_either_way: 두 사용자 중 한쪽이라도 상대를 차단했는지 확인하는 함수.
            accept_request: 친구 요청을 수락 처리(양방향 대화방 생성 등)하는 함수.
        """
        self._connection_factory = connection_factory
        self._now_string = now_string
        self._blocked_either_way = blocked_either_way
        self._accept_request = accept_request

    def send_request(self, requester_id: int, requester_username: str, target_username: str):
        """친구 요청을 보낸다.

        상대가 이미 나에게 보낸 보류 요청이 있으면 새로 만들지 않고 그 요청을 자동 수락한다.

        Returns:
            알림 대상과 자동 수락 여부를 담은 FriendRequestOutcome.

        Raises:
            FriendServiceError: 입력이 비었거나, 자기 자신·차단 관계·이미 친구·중복 요청인 경우.
        """
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
            # 채팅방이 남아 있는지와 친구 관계는 별개다. 숨긴 과거 대화방이 있어도
            # 친구를 삭제한 뒤 다시 요청할 수 있어야 하므로, 수락된 요청이 있는지만 확인한다.
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
            # 상대가 이미 나에게 요청을 보내 둔 경우를 찾는다.
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
            # 예전에 거절·취소돼 남은 요청 행이 있으면 새로 만들지 않고 보류 상태로 되돌린다.
            # (requester, addressee 조합이 유일해야 하기 때문이다.)
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
        """받은 친구 요청을 수락하거나 거절한다. 수신자 본인만 처리할 수 있다.

        Returns:
            요청을 보낸 사용자 ID. 호출자가 결과를 실시간으로 알릴 때 쓴다.
        """
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
        """내가 보낸 보류 중인 요청을 취소한다.

        Returns:
            요청을 받았던 사용자 ID.
        """
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
        """수락된 친구 목록을 돌려준다.

        채팅방을 숨겼는지와 상관없이 friend_requests의 실제 친구 관계를 기준으로 한다.
        각 항목에는 내가 상대를 차단했는지, 상대가 나를 차단했는지도 함께 담는다.
        """
        with self._connection_factory() as conn:
            # 내가 요청한 쪽이든 받은 쪽이든, CASE로 상대방 계정을 peer에 맞춰 조인한다.
            # 표시 이름이 없으면 아이디 순으로 정렬한다.
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
        """친구 관계만 끊는다. 채팅방 숨김·삭제와는 별개의 동작이다."""
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

    def open_friend_conversation(self, user_id: int, target_id: int) -> int:
        """친구와의 숨긴 1:1 대화방을 내 목록에 다시 보이게 한다.

        Returns:
            다시 열린 대화방 ID.
        """
        with self._connection_factory() as conn:
            friendship = conn.execute(
                """
                SELECT 1 FROM friend_requests
                WHERE status = 'accepted'
                  AND ((requester_id = %s AND addressee_id = %s)
                    OR (requester_id = %s AND addressee_id = %s))
                """,
                (user_id, target_id, target_id, user_id),
            ).fetchone()
            if not friendship:
                raise FriendServiceError("친구 관계를 찾을 수 없습니다.", 404)

            conversation = conn.execute(
                """
                SELECT conversation.id
                FROM conversations conversation
                JOIN conversation_members mine
                  ON mine.conversation_id = conversation.id AND mine.user_id = %s
                JOIN conversation_members peer
                  ON peer.conversation_id = conversation.id AND peer.user_id = %s
                WHERE conversation.is_group = FALSE
                ORDER BY conversation.id DESC
                LIMIT 1
                """,
                (user_id, target_id),
            ).fetchone()
            if not conversation:
                raise FriendServiceError("대화방을 찾을 수 없습니다.", 404)

            conn.execute(
                "UPDATE conversation_members SET hidden_at = NULL WHERE conversation_id = %s AND user_id = %s",
                (conversation["id"], user_id),
            )
            conn.commit()
        return conversation["id"]

    def list_blocks(self, user_id: int) -> list[dict]:
        """내가 직접 차단한 사용자 목록을 최근에 차단한 순서로 돌려준다."""
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT users.id, users.display_name, users.username FROM blocks JOIN users ON users.id = blocks.blocked_id WHERE blocks.blocker_id = %s ORDER BY blocks.created_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def block(self, user_id: int, target_id: int | None) -> int:
        """사용자를 차단한다. 자기 자신, 존재하지 않는 사용자는 거부하고 이미 차단한 경우는 조용히 넘어간다."""
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
        """내가 만든 차단만 해제한다."""
        with self._connection_factory() as conn:
            conn.execute(
                "DELETE FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
                (user_id, target_id),
            )
            conn.commit()

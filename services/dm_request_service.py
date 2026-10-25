"""1:1 메시지 요청을 관리하는 서비스.

맞팔(서로 팔로우)이 아닌 상대에게 처음 메시지를 보내면 1:1 대화방이 'pending'(수락 대기) 상태로 만들어지고,
받는 사람 메시지함에 '메시지 요청'으로 나타난다. 받는 사람이 수락하면 'active'가 되어 보통 대화방이 되고,
거절하면 'declined'가 되어 받는 사람은 답장할 수 없으며 보낸 사람만 제한된 수만큼 일방적으로 보낼 수 있다.

기존에 있던 대화방은 모두 'active'(컬럼 기본값)라서 이 규칙의 영향을 받지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

STATE_ACTIVE = "active"
STATE_PENDING = "pending"
STATE_DECLINED = "declined"

# 수락 전에 보낸 사람이 보낼 수 있는 최대 메시지 수, 거절된 뒤 보낸 사람이 보낼 수 있는 최대(누적) 메시지 수.
PENDING_MESSAGE_LIMIT = 5
DECLINED_MESSAGE_LIMIT = 30


class DmRequestError(Exception):
    """메시지 요청의 예상 가능한 검증 오류. HTTP 상태 코드를 함께 담는다."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class StartOutcome:
    """대화 시작 결과.

    Attributes:
        conversation_id: 열거나 새로 만든 1:1 대화방 ID.
        state: 대화방 상태(active / pending / declined).
        created: 이번 호출로 새로 만들어졌는지 여부.
    """

    conversation_id: int
    state: str
    created: bool


def send_block_reason(conn, conversation_id: int, user_id: int):
    """이 사용자가 지금 이 대화방에 메시지를 보낼 수 없으면 (상태 코드, 안내 문구)를, 보낼 수 있으면 None을 돌려준다.

    active 방(그룹 포함)은 항상 None이다. 수락 대기·거절된 방에서는 받는 사람은 보낼 수 없고,
    보낸 사람은 정해진 개수까지만 보낼 수 있다.
    """
    conv = conn.execute(
        "SELECT dm_state, dm_requester_id FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    if not conv or conv["dm_state"] == STATE_ACTIVE:
        return None
    if conv["dm_requester_id"] != user_id:
        if conv["dm_state"] == STATE_PENDING:
            return (403, "메시지 요청을 수락해야 답장할 수 있습니다.")
        return (403, "거절한 대화에는 답장할 수 없습니다.")
    limit = PENDING_MESSAGE_LIMIT if conv["dm_state"] == STATE_PENDING else DECLINED_MESSAGE_LIMIT
    sent = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = %s AND sender_id = %s AND message_type = 'user'",
        (conversation_id, user_id),
    ).fetchone()["n"]
    if sent >= limit:
        return (403, "상대가 수락하기 전에는 메시지를 더 보낼 수 없습니다.")
    return None


def recipient_can_see(conn, conversation_id: int, user_id: int) -> bool:
    """이 사용자의 대화 목록에 이 대화방이 보여야 하는지(수락 대기·거절된 방은 보낸 사람에게만)."""
    conv = conn.execute(
        "SELECT dm_state, dm_requester_id FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    return bool(conv) and (conv["dm_state"] == STATE_ACTIVE or conv["dm_requester_id"] == user_id)


class DmRequestService:
    """메시지 요청의 생성·목록·수락·거절을 처리한다."""

    def __init__(self, connection_factory, now_string, blocked_either_way, is_mutual) -> None:
        """서비스가 쓸 DB 연결과 보조 함수를 주입받는다.

        Args:
            connection_factory: DB 연결을 만들어 주는 함수.
            now_string: 현재 시각 문자열을 돌려주는 함수.
            blocked_either_way: 차단 관계 확인 함수(conn, a, b).
            is_mutual: 맞팔 여부 확인 함수(conn, a, b).
        """
        self._connection_factory = connection_factory
        self._now_string = now_string
        self._blocked_either_way = blocked_either_way
        self._is_mutual = is_mutual

    def start_conversation(self, user_id: int, target_id) -> StartOutcome:
        """상대와의 1:1 대화방을 열고, 없으면 만든다.

        맞팔이면 바로 쓰는 방(active)으로, 아니면 수락 대기 방(pending)으로 만든다.
        이미 방이 있으면 그 방을 내 목록에 다시 나타나게 하고 현재 상태 그대로 돌려준다.

        Raises:
            DmRequestError: 자기 자신·없는 사용자·정지 계정·차단 관계인 경우.
        """
        if not isinstance(target_id, int) or isinstance(target_id, bool):
            raise DmRequestError("올바른 사용자가 아닙니다.")
        if target_id == user_id:
            raise DmRequestError("자기 자신과는 대화할 수 없습니다.")
        with self._connection_factory() as conn:
            target = conn.execute(
                "SELECT id, is_suspended FROM users WHERE id = %s", (target_id,)
            ).fetchone()
            if not target or target["is_suspended"]:
                raise DmRequestError("사용자를 찾을 수 없습니다.", 404)
            if self._blocked_either_way(conn, user_id, target_id):
                raise DmRequestError("차단 관계에서는 메시지를 보낼 수 없습니다.", 403)

            existing = conn.execute(
                """
                SELECT c.id, c.dm_state FROM conversations c
                JOIN conversation_members a ON a.conversation_id = c.id AND a.user_id = %s
                JOIN conversation_members b ON b.conversation_id = c.id AND b.user_id = %s
                WHERE NOT c.is_group
                ORDER BY c.id LIMIT 1
                """,
                (user_id, target_id),
            ).fetchone()
            if existing:
                # 내가 숨겨 뒀다면 다시 보이게 한다. 상대 쪽 숨김 상태는 건드리지 않는다.
                conn.execute(
                    "UPDATE conversation_members SET hidden_at = NULL WHERE conversation_id = %s AND user_id = %s",
                    (existing["id"], user_id),
                )
                conn.commit()
                return StartOutcome(existing["id"], existing["dm_state"], created=False)

            state = STATE_ACTIVE if self._is_mutual(conn, user_id, target_id) else STATE_PENDING
            now = self._now_string()
            conversation = conn.execute(
                "INSERT INTO conversations (is_group, name, created_at, dm_state, dm_requester_id)"
                " VALUES (FALSE, NULL, %s, %s, %s) RETURNING id",
                (now, state, user_id if state != STATE_ACTIVE else None),
            ).fetchone()
            for member_id in (user_id, target_id):
                # 수락 대기 방은 받는 사람의 대화 목록에 나타나지 않도록 숨김 처리해서 시작한다.
                hidden_at = now if (state != STATE_ACTIVE and member_id == target_id) else None
                conn.execute(
                    "INSERT INTO conversation_members (conversation_id, user_id, last_read_message_id, hidden_at, joined_at)"
                    " VALUES (%s, %s, 0, %s, %s)",
                    (conversation["id"], member_id, hidden_at, now),
                )
            conn.commit()
        return StartOutcome(conversation["id"], state, created=True)

    def list_requests(self, user_id: int) -> dict:
        """내가 받은 메시지 요청(수락 대기)과 내가 거절한 요청 목록을 돌려준다. 항목마다 미리보기 메시지를 담는다."""
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.dm_state, c.last_activity_id,
                       u.id AS user_id, u.username, u.display_name, u.profile_image,
                       (SELECT COUNT(*) FROM messages m
                         WHERE m.conversation_id = c.id AND m.sender_id = u.id) AS message_count,
                       last_msg.text AS last_text, last_msg.image AS last_image, last_msg.video AS last_video,
                       last_msg.audio AS last_audio, last_msg.file_name AS last_file_name,
                       last_msg.time AS last_time
                FROM conversations c
                JOIN conversation_members me ON me.conversation_id = c.id AND me.user_id = %s
                JOIN users u ON u.id = c.dm_requester_id
                LEFT JOIN LATERAL (
                    SELECT text, image, video, audio, file_name, time FROM messages
                    WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1
                ) last_msg ON TRUE
                WHERE NOT c.is_group AND c.dm_state IN ('pending', 'declined')
                  AND c.dm_requester_id != %s AND NOT u.is_suspended
                  AND NOT EXISTS (
                      SELECT 1 FROM blocks b
                      WHERE (b.blocker_id = %s AND b.blocked_id = u.id)
                         OR (b.blocker_id = u.id AND b.blocked_id = %s))
                ORDER BY c.last_activity_id DESC, c.id DESC
                """,
                (user_id, user_id, user_id, user_id),
            ).fetchall()
        pending, declined = [], []
        for row in rows:
            item = {
                "conversationId": row["id"],
                "messageCount": row["message_count"],
                "preview": self._preview(row),
                "lastTime": row["last_time"] or "",
                "user": {
                    "id": row["user_id"],
                    "username": row["username"],
                    "displayName": row["display_name"] or row["username"],
                    "profileImage": row["profile_image"],
                },
            }
            (pending if row["dm_state"] == STATE_PENDING else declined).append(item)
        return {"pending": pending, "declined": declined}

    @staticmethod
    def _preview(row) -> str:
        if row["last_audio"]:
            return "음성 메시지"
        if row["last_file_name"]:
            return "파일"
        if row["last_video"]:
            return "동영상"
        if row["last_image"]:
            return "사진"
        return (row["last_text"] or "")[:120]

    def pending_count(self, user_id: int) -> int:
        """내가 받은, 수락을 기다리는 메시지 요청 수(메시지함 배지용)."""
        with self._connection_factory() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM conversations c
                JOIN conversation_members me ON me.conversation_id = c.id AND me.user_id = %s
                WHERE NOT c.is_group AND c.dm_state = 'pending' AND c.dm_requester_id != %s
                """,
                (user_id, user_id),
            ).fetchone()
        return row["n"]

    def respond(self, user_id: int, conversation_id: int, accept: bool) -> int:
        """받은 메시지 요청을 수락하거나 거절한다. 거절한 요청도 나중에 수락할 수 있다.

        Returns:
            알림을 보낼 상대(요청한 사람)의 사용자 ID.

        Raises:
            DmRequestError: 내가 받은 요청이 아니면 404.
        """
        with self._connection_factory() as conn:
            conv = conn.execute(
                """
                SELECT c.dm_state, c.dm_requester_id FROM conversations c
                JOIN conversation_members me ON me.conversation_id = c.id AND me.user_id = %s
                WHERE c.id = %s AND NOT c.is_group
                """,
                (user_id, conversation_id),
            ).fetchone()
            if not conv or conv["dm_state"] == STATE_ACTIVE or conv["dm_requester_id"] == user_id:
                raise DmRequestError("요청을 찾을 수 없습니다.", 404)
            if accept:
                conn.execute(
                    "UPDATE conversations SET dm_state = 'active' WHERE id = %s", (conversation_id,)
                )
                # 수락하면 내 대화 목록에 나타난다.
                conn.execute(
                    "UPDATE conversation_members SET hidden_at = NULL WHERE conversation_id = %s AND user_id = %s",
                    (conversation_id, user_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET dm_state = 'declined' WHERE id = %s",
                    (conversation_id,),
                )
            conn.commit()
        return conv["dm_requester_id"]

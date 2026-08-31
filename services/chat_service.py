"""대화방의 멤버십·읽음 위치·공용 설정을 한 트랜잭션으로 관리합니다."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LeaveConversationResult:
    """나가기 처리 뒤 호출자가 정리해야 할 대화방 상태입니다."""
    conversation_deleted: bool
    image_paths: list[str]


class ChatServiceError(Exception):
    """클라이언트에 안전하게 전달할 수 있는 대화방 도메인 오류입니다."""
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class ChatService:
    """채팅방 상태 변경 전에 멤버·방장·종료 여부를 검사합니다."""
    SUPPORTED_THEMES = {
        "default",
        "heart",
        "teddy",
        "glass",
        "aurora",
        "mono",
        "spring",
        "summer",
        "autumn",
        "winter",
        "christmas",
        "halloween",
    }

    def __init__(self, connection_factory, now_string=None, default_profile_image=None):
        self._connection_factory = connection_factory
        self._now_string = now_string
        self._default_profile_image = default_profile_image

    def is_member(self, conversation_id: int, user_id: int) -> bool:
        """후속 메시지·설정 API가 사용할 최소 멤버십 검사입니다."""
        with self._connection_factory() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                    (conversation_id, user_id),
                ).fetchone()
                is not None
            )

    def member_ids(self, conversation_id: int) -> list[int]:
        """실시간 이벤트를 보낼 현재 대화방 참여자 ID를 반환합니다."""
        with self._connection_factory() as conn:
            rows = conn.execute(
                "SELECT user_id FROM conversation_members WHERE conversation_id = %s",
                (conversation_id,),
            ).fetchall()
        return [row["user_id"] for row in rows]

    def mark_read(self, conversation_id: int, user_id: int) -> bool:
        """대화방 멤버의 읽음 위치를 최신 메시지까지 갱신한다."""
        with self._connection_factory() as conn:
            member = conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if not member:
                return False
            latest = conn.execute(
                "SELECT MAX(id) AS max_id FROM messages WHERE conversation_id = %s",
                (conversation_id,),
            ).fetchone()
            latest_id = latest["max_id"] if latest and latest["max_id"] else 0
            conn.execute(
                "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
                (latest_id, conversation_id, user_id),
            )
            conn.commit()
        return True

    def update_preferences(
        self,
        conversation_id: int,
        user_id: int,
        *,
        is_muted: bool | None = None,
        is_pinned: bool | None = None,
    ) -> bool:
        """대화방 멤버의 개인 설정만 변경한다."""
        if is_muted is None and is_pinned is None:
            raise ChatServiceError("변경할 설정이 없습니다.")
        with self._connection_factory() as conn:
            member = conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if not member:
                return False
            if is_muted is not None:
                conn.execute(
                    "UPDATE conversation_members SET is_muted = %s WHERE conversation_id = %s AND user_id = %s",
                    (is_muted, conversation_id, user_id),
                )
            if is_pinned is not None:
                conn.execute(
                    "UPDATE conversation_members SET is_pinned = %s WHERE conversation_id = %s AND user_id = %s",
                    (is_pinned, conversation_id, user_id),
                )
            conn.commit()
        return True

    def rename_group(self, conversation_id: int, owner_id: int, name: str) -> None:
        """방장만 활성 그룹 대화방의 이름을 변경할 수 있도록 검증한다."""
        if not name:
            raise ChatServiceError("방 이름을 입력해주세요.")
        with self._connection_factory() as conn:
            if not conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, owner_id),
            ).fetchone():
                raise ChatServiceError("대화방을 찾을 수 없습니다.", 404)
            conversation = conn.execute(
                "SELECT is_group, owner_id, is_disabled FROM conversations WHERE id = %s",
                (conversation_id,),
            ).fetchone()
            if not conversation or not conversation["is_group"]:
                raise ChatServiceError("그룹 채팅만 이름을 바꿀 수 있습니다.")
            if conversation["owner_id"] != owner_id:
                raise ChatServiceError("방장만 그룹 이름을 바꿀 수 있습니다.", 403)
            if conversation["is_disabled"]:
                raise ChatServiceError("종료된 그룹 채팅방은 정보를 변경할 수 없습니다.", 403)
            conn.execute(
                "UPDATE conversations SET name = %s WHERE id = %s",
                (name, conversation_id),
            )
            conn.commit()

    def hide_conversation(self, conversation_id: int, user_id: int) -> bool:
        """멤버에게만 대화방 숨김 상태를 적용한다."""
        if self._now_string is None:
            raise RuntimeError("대화방 숨김에 필요한 서비스 설정이 없습니다.")
        with self._connection_factory() as conn:
            member = conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if not member:
                return False
            conn.execute(
                "UPDATE conversation_members SET hidden_at = %s WHERE conversation_id = %s AND user_id = %s",
                (self._now_string(), conversation_id, user_id),
            )
            conn.commit()
        return True

    def leave_conversation(
        self, conversation_id: int, user_id: int, create_leave_message
    ) -> LeaveConversationResult:
        """멤버 탈퇴, 방장 위임, 빈 대화방 정리를 하나의 트랜잭션으로 처리한다."""
        with self._connection_factory() as conn:
            membership = conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if not membership:
                raise ChatServiceError("대화방을 찾을 수 없습니다.", 404)
            conversation = conn.execute(
                "SELECT owner_id, is_group FROM conversations WHERE id = %s",
                (conversation_id,),
            ).fetchone()
            if not conversation:
                raise ChatServiceError("대화방을 찾을 수 없습니다.", 404)
            if conversation["is_group"]:
                user = conn.execute(
                    "SELECT display_name, username FROM users WHERE id = %s", (user_id,)
                ).fetchone()
                name = user["display_name"] or user["username"]
                create_leave_message(conn, conversation_id, name, user_id)
            conn.execute(
                "DELETE FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            if conversation["is_group"] and conversation["owner_id"] == user_id:
                new_owner = conn.execute(
                    "SELECT user_id FROM conversation_members WHERE conversation_id = %s ORDER BY joined_at ASC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                if new_owner:
                    conn.execute(
                        "UPDATE conversations SET owner_id = %s WHERE id = %s",
                        (new_owner["user_id"], conversation_id),
                    )
            remaining_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM conversation_members WHERE conversation_id = %s",
                (conversation_id,),
            ).fetchone()
            remaining = remaining_row["cnt"] if remaining_row else 0
            image_paths = []
            if remaining == 0:
                image_paths = [
                    row["image"]
                    for row in conn.execute(
                        "SELECT image FROM messages WHERE conversation_id = %s AND image IS NOT NULL",
                        (conversation_id,),
                    ).fetchall()
                ]
                conn.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            conn.commit()
        return LeaveConversationResult(remaining == 0, image_paths)

    def disable_group(self, conversation_id: int, owner_id: int, create_disabled_message) -> None:
        """방장만 그룹 채팅을 종료하고, 종료 기록까지 같은 트랜잭션으로 남긴다."""
        with self._connection_factory() as conn:
            conversation = conn.execute(
                "SELECT is_group, owner_id, is_disabled FROM conversations WHERE id = %s",
                (conversation_id,),
            ).fetchone()
            member = conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, owner_id),
            ).fetchone()
            if not conversation or not member:
                raise ChatServiceError("대화방을 찾을 수 없습니다.", 404)
            if not conversation["is_group"] or conversation["owner_id"] != owner_id:
                raise ChatServiceError("그룹 방장만 채팅방을 종료할 수 있습니다.", 403)
            if conversation["is_disabled"]:
                raise ChatServiceError("이미 종료된 채팅방입니다.")
            user = conn.execute(
                "SELECT display_name, username FROM users WHERE id = %s", (owner_id,)
            ).fetchone()
            name = user["display_name"] or user["username"]
            conn.execute(
                "UPDATE conversations SET is_disabled = TRUE, disabled_by = %s WHERE id = %s",
                (owner_id, conversation_id),
            )
            create_disabled_message(conn, conversation_id, name, owner_id)
            conn.commit()

    def update_theme(
        self, conversation_id: int, user_id: int, theme: str, create_theme_message
    ) -> None:
        """활성 대화방의 공용 테마를 멤버가 변경하도록 처리한다."""
        if theme not in self.SUPPORTED_THEMES:
            raise ChatServiceError("지원하지 않는 채팅 테마입니다.")
        with self._connection_factory() as conn:
            member = conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if not member:
                raise ChatServiceError("대화방을 찾을 수 없습니다.", 404)
            conversation = conn.execute(
                "SELECT is_disabled FROM conversations WHERE id = %s", (conversation_id,)
            ).fetchone()
            if conversation and conversation["is_disabled"]:
                raise ChatServiceError("종료된 채팅방에서는 테마를 바꿀 수 없습니다.", 403)
            user = conn.execute(
                "SELECT display_name, username FROM users WHERE id = %s", (user_id,)
            ).fetchone()
            name = user["display_name"] or user["username"]
            conn.execute(
                "UPDATE conversations SET chat_theme = %s WHERE id = %s", (theme, conversation_id)
            )
            create_theme_message(conn, conversation_id, name, user_id)
            conn.commit()

    def create_group(self, owner_id: int, name: str, usernames: list[str]) -> int:
        """방장 포함 최소 3명의 새 그룹 채팅방을 생성합니다."""
        if not name:
            raise ChatServiceError("방 이름을 입력해주세요.")
        if self._now_string is None or self._default_profile_image is None:
            raise RuntimeError("그룹 채팅 생성에 필요한 서비스 설정이 없습니다.")
        with self._connection_factory() as conn:
            # set을 사용해 같은 사용자를 여러 번 넣어도 멤버십이 중복되지 않게 합니다.
            member_ids = {owner_id}
            for username in usernames:
                row = conn.execute(
                    "SELECT id FROM users WHERE username = %s", (username,)
                ).fetchone()
                if not row:
                    raise ChatServiceError(f"'{username}' 사용자를 찾을 수 없습니다.")
                member_ids.add(row["id"])
            if len(member_ids) < 3:
                raise ChatServiceError("그룹 채팅은 3명 이상이어야 합니다.")
            conversation = conn.execute(
                "INSERT INTO conversations (is_group, name, owner_id, profile_image, created_at) VALUES (TRUE, %s, %s, %s, %s) RETURNING id",
                (name, owner_id, self._default_profile_image, self._now_string()),
            ).fetchone()
            conversation_id = conversation["id"]
            for member_id in member_ids:
                conn.execute(
                    "INSERT INTO conversation_members (conversation_id, user_id, last_read_message_id, joined_at) VALUES (%s, %s, 0, %s)",
                    (conversation_id, member_id, self._now_string()),
                )
            conn.commit()
        return conversation_id

    def invite_members(self, conversation_id: int, actor_id: int, usernames: list[str]) -> None:
        """활성 그룹에 아직 참여하지 않은 사용자만 초대합니다."""
        with self._connection_factory() as conn:
            if not conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, actor_id),
            ).fetchone():
                raise ChatServiceError("대화방을 찾을 수 없습니다.", 404)
            conversation = conn.execute(
                "SELECT is_group, is_disabled FROM conversations WHERE id = %s", (conversation_id,)
            ).fetchone()
            if not conversation or not conversation["is_group"]:
                raise ChatServiceError("그룹 채팅에서만 멤버를 초대할 수 있습니다.")
            if conversation["is_disabled"]:
                raise ChatServiceError("종료된 그룹 채팅방에는 멤버를 초대할 수 없습니다.", 403)
            for username in usernames:
                user = conn.execute(
                    "SELECT id FROM users WHERE username = %s", (username,)
                ).fetchone()
                if not user:
                    raise ChatServiceError(f"'{username}' 사용자를 찾을 수 없습니다.")
                member = conn.execute(
                    "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                    (conversation_id, user["id"]),
                ).fetchone()
                if member:
                    continue
                conn.execute(
                    "INSERT INTO conversation_members (conversation_id, user_id, last_read_message_id, joined_at) VALUES (%s, %s, 0, %s)",
                    (conversation_id, user["id"], self._now_string()),
                )
            conn.commit()

    def remove_member(self, conversation_id: int, owner_id: int, member_user_id: int) -> None:
        """방장이 다른 멤버만 내보내도록 검증한 뒤 멤버십을 제거합니다."""
        with self._connection_factory() as conn:
            if not conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, owner_id),
            ).fetchone():
                raise ChatServiceError("대화방을 찾을 수 없습니다.", 404)
            conversation = conn.execute(
                "SELECT is_group, owner_id, is_disabled FROM conversations WHERE id = %s",
                (conversation_id,),
            ).fetchone()
            if not conversation or not conversation["is_group"]:
                raise ChatServiceError("그룹 채팅에서만 멤버를 내보낼 수 있습니다.")
            if conversation["owner_id"] != owner_id:
                raise ChatServiceError("방장만 멤버를 내보낼 수 있습니다.", 403)
            if conversation["is_disabled"]:
                raise ChatServiceError("종료된 그룹 채팅방은 멤버를 변경할 수 없습니다.", 403)
            if member_user_id == owner_id:
                raise ChatServiceError("본인은 내보낼 수 없습니다. 나가기 기능을 이용해주세요.")
            if not conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, member_user_id),
            ).fetchone():
                raise ChatServiceError("해당 멤버를 찾을 수 없습니다.", 404)
            conn.execute(
                "DELETE FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, member_user_id),
            )
            conn.commit()

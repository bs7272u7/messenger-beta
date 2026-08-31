"""메시지 수정·삭제·반응·신고처럼 권한 확인이 필요한 상태 변경을 관리합니다."""

import json


class MessageServiceError(Exception):
    """API 응답으로 변환할 수 있는 메시지 도메인 오류입니다."""
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class MessageService:
    """메시지와 대화방 멤버십을 함께 확인해 다른 방의 데이터를 보호합니다."""
    REPORT_REASONS = {"스팸", "욕설·괴롭힘", "부적절한 콘텐츠", "사칭", "기타"}

    def __init__(
        self,
        connection_factory=None,
        now_string=None,
        timestamp_factory=None,
        legacy_labels_factory=None,
        unhide_conversation=None,
    ):
        self._connection_factory = connection_factory
        self._now_string = now_string
        self._timestamp_factory = timestamp_factory
        self._legacy_labels_factory = legacy_labels_factory
        self._unhide_conversation = unhide_conversation

    @staticmethod
    def decode_json(value, fallback):
        """과거 데이터의 비정상 JSON이 화면 렌더링을 중단시키지 않게 합니다."""
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    def toggle_reaction(self, message_id: int, user_id: int, emoji: str) -> tuple[int, list]:
        """대화방 멤버가 메시지 반응을 추가하거나 취소한다."""
        if not isinstance(emoji, str) or not emoji.strip() or len(emoji) > 32:
            raise MessageServiceError("올바른 반응을 선택해주세요.")
        if self._connection_factory is None:
            raise RuntimeError("메시지 서비스에 데이터베이스 연결이 설정되지 않았습니다.")
        with self._connection_factory() as conn:
            message = conn.execute(
                """
                SELECT messages.* FROM messages
                JOIN conversation_members
                  ON conversation_members.conversation_id = messages.conversation_id
                WHERE messages.id = %s AND conversation_members.user_id = %s
                """,
                (message_id, user_id),
            ).fetchone()
            if not message:
                raise MessageServiceError("메시지를 찾을 수 없습니다.", 404)
            reactions = self.decode_json(message["reactions"], [])
            if not isinstance(reactions, list):
                reactions = []
            if emoji in reactions:
                reactions.remove(emoji)
            else:
                reactions.append(emoji)
            conn.execute(
                "UPDATE messages SET reactions = %s WHERE id = %s",
                (json.dumps(reactions), message_id),
            )
            conn.commit()
        return message["conversation_id"], reactions

    def toggle_pin(self, message_id: int, user_id: int) -> tuple[int, bool]:
        """대화방 멤버만 메시지 고정 상태를 반전할 수 있게 합니다."""
        """대화방 멤버가 메시지를 고정하거나 기존 고정을 해제한다."""
        if self._connection_factory is None:
            raise RuntimeError("메시지 서비스에 데이터베이스 연결이 설정되지 않았습니다.")
        with self._connection_factory() as conn:
            message = conn.execute(
                """
                SELECT messages.* FROM messages
                JOIN conversation_members
                  ON conversation_members.conversation_id = messages.conversation_id
                WHERE messages.id = %s AND conversation_members.user_id = %s
                """,
                (message_id, user_id),
            ).fetchone()
            if not message:
                raise MessageServiceError("메시지를 찾을 수 없습니다.", 404)
            conversation_id = message["conversation_id"]
            now_pinned = not bool(message["pinned"])
            conn.execute(
                "UPDATE messages SET pinned = FALSE WHERE conversation_id = %s",
                (conversation_id,),
            )
            if now_pinned:
                conn.execute("UPDATE messages SET pinned = TRUE WHERE id = %s", (message_id,))
            conn.commit()
        return conversation_id, now_pinned

    def edit_message(self, message_id: int, user_id: int, text: str) -> int:
        """작성자 본인의 텍스트 메시지만 수정하고 대화방 ID를 반환합니다."""
        """작성자만 메시지 본문을 수정하도록 처리한다."""
        if not text:
            raise MessageServiceError("메시지 내용을 입력해주세요.")
        if len(text) > 5000:
            raise MessageServiceError("메시지는 5,000자 이하로 입력해주세요.")
        if self._connection_factory is None:
            raise RuntimeError("메시지 서비스에 데이터베이스 연결이 설정되지 않았습니다.")
        with self._connection_factory() as conn:
            message = conn.execute(
                """
                SELECT messages.* FROM messages
                JOIN conversation_members
                  ON conversation_members.conversation_id = messages.conversation_id
                WHERE messages.id = %s AND conversation_members.user_id = %s
                """,
                (message_id, user_id),
            ).fetchone()
            if not message:
                raise MessageServiceError("메시지를 찾을 수 없습니다.", 404)
            if message["sender_id"] != user_id:
                raise MessageServiceError("본인 메시지만 수정할 수 있습니다.", 403)
            conn.execute(
                "UPDATE messages SET text = %s, edited = TRUE WHERE id = %s",
                (text, message_id),
            )
            conn.commit()
        return message["conversation_id"]

    def delete_message(self, message_id: int, user_id: int) -> tuple[int, str | None]:
        """작성자 본인의 메시지를 지우고, 후처리에 필요한 첨부 경로를 반환합니다."""
        """작성자만 메시지를 삭제하고, 후속 파일 정리에 필요한 경로를 돌려준다."""
        if self._connection_factory is None:
            raise RuntimeError("메시지 서비스에 데이터베이스 연결이 설정되지 않았습니다.")
        with self._connection_factory() as conn:
            message = conn.execute(
                """
                SELECT messages.* FROM messages
                JOIN conversation_members
                  ON conversation_members.conversation_id = messages.conversation_id
                WHERE messages.id = %s AND conversation_members.user_id = %s
                """,
                (message_id, user_id),
            ).fetchone()
            if not message:
                raise MessageServiceError("메시지를 찾을 수 없습니다.", 404)
            if message["sender_id"] != user_id:
                raise MessageServiceError("본인 메시지만 삭제할 수 있습니다.", 403)
            conn.execute("DELETE FROM messages WHERE id = %s", (message_id,))
            conn.commit()
        return message["conversation_id"], message["image"]

    def report_message(self, message_id: int, reporter_id: int, reason: str, detail: str) -> None:
        """대화방 멤버의 신고만 저장하고, 허용된 사유와 상세 길이를 검증합니다."""
        """대화방 멤버가 타인의 메시지를 한 번만 신고하도록 처리한다."""
        if reason not in self.REPORT_REASONS:
            raise MessageServiceError("신고 사유를 선택해주세요.")
        if len(detail) > 1000:
            raise MessageServiceError("신고 내용은 1,000자 이하로 입력해주세요.")
        if self._connection_factory is None or self._now_string is None:
            raise RuntimeError("메시지 신고에 필요한 서비스 설정이 없습니다.")
        with self._connection_factory() as conn:
            message = conn.execute(
                """
                SELECT messages.* FROM messages
                JOIN conversation_members
                  ON conversation_members.conversation_id = messages.conversation_id
                WHERE messages.id = %s AND conversation_members.user_id = %s
                """,
                (message_id, reporter_id),
            ).fetchone()
            if not message:
                raise MessageServiceError("메시지를 찾을 수 없습니다.", 404)
            if message["sender_id"] == reporter_id:
                raise MessageServiceError("내 메시지는 신고할 수 없습니다.")
            conn.execute(
                """INSERT INTO reports (reporter_id, message_id, reason, detail, created_at)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (reporter_id, message_id) DO NOTHING""",
                (reporter_id, message_id, reason, detail or None, self._now_string()),
            )
            conn.commit()

    def forward_message(self, message_id: int, user_id: int, target_conversation_id: int) -> int:
        """원본·대상 대화방 모두의 멤버인지 확인한 뒤 전달 메시지를 만듭니다."""
        """접근 가능한 메시지를 참여 중인 대화방으로 복사한다."""
        if not target_conversation_id:
            raise MessageServiceError("전달할 채팅방을 선택해주세요.")
        if any(
            callback is None
            for callback in (
                self._connection_factory,
                self._timestamp_factory,
                self._legacy_labels_factory,
                self._unhide_conversation,
            )
        ):
            raise RuntimeError("메시지 전달에 필요한 서비스 설정이 없습니다.")
        with self._connection_factory() as conn:
            source = conn.execute(
                """
                SELECT messages.* FROM messages
                JOIN conversation_members
                  ON conversation_members.conversation_id = messages.conversation_id
                WHERE messages.id = %s AND conversation_members.user_id = %s
                """,
                (message_id, user_id),
            ).fetchone()
            target_member = conn.execute(
                "SELECT 1 FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
                (target_conversation_id, user_id),
            ).fetchone()
            if not source or not target_member:
                raise MessageServiceError("메시지 또는 채팅방을 찾을 수 없습니다.", 404)
            sent_at = self._timestamp_factory()
            time_label, date_label = self._legacy_labels_factory(sent_at)
            row = conn.execute(
                """
                INSERT INTO messages (conversation_id, sender_id, text, image, video, file_path, file_name, file_size, time, date, sent_at, reply, edited, pinned, reactions)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, FALSE, FALSE, %s) RETURNING id
                """,
                (
                    target_conversation_id,
                    user_id,
                    source["text"],
                    source["image"],
                    source["video"],
                    source["file_path"],
                    source["file_name"],
                    source["file_size"],
                    time_label,
                    date_label,
                    sent_at,
                    json.dumps([]),
                ),
            ).fetchone()
            conn.execute(
                "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
                (row["id"], target_conversation_id, user_id),
            )
            conn.execute(
                "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
                (row["id"], target_conversation_id),
            )
            self._unhide_conversation(conn, target_conversation_id)
            conn.commit()
        return target_conversation_id

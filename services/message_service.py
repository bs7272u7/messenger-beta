"""메시지 수정·삭제·반응·고정·신고·전달처럼 권한 확인이 필요한 상태 변경을 처리하는 서비스.

모든 메서드는 '요청한 사용자가 그 메시지가 있는 대화방의 멤버인가'를 먼저 확인한다.
멤버가 아니면 메시지가 있는지조차 알 수 없도록 같은 404로 응답한다.
"""

import json


class MessageServiceError(Exception):
    """API 응답으로 바꿀 수 있는 메시지 도메인 오류. HTTP 상태 코드를 함께 담는다."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class MessageService:
    """메시지와 대화방 멤버십을 함께 확인해 다른 대화방의 데이터를 보호한다."""

    # 신고 화면의 선택지와 같은 값이어야 한다. 목록에 없는 사유는 거부한다.
    REPORT_REASONS = {"스팸", "욕설·괴롭힘", "부적절한 콘텐츠", "사칭", "기타"}

    def __init__(
        self,
        connection_factory=None,
        now_string=None,
        timestamp_factory=None,
        legacy_labels_factory=None,
        unhide_conversation=None,
    ):
        """서비스가 쓸 DB 연결과 보조 함수를 주입받는다.

        모두 선택 인자라서, 필요한 값이 없는 상태로 해당 기능을 호출하면 RuntimeError로 알려 준다.

        Args:
            connection_factory: DB 연결을 만들어 주는 함수.
            now_string: 현재 시각 문자열을 돌려주는 함수.
            timestamp_factory: 메시지 기준 시각(UTC epoch 밀리초)을 만드는 함수.
            legacy_labels_factory: 밀리초 시각에서 예전 time/date 컬럼용 문자열을 만드는 함수.
            unhide_conversation: 숨겨 둔 대화방을 다시 보이게 하는 함수.
        """
        self._connection_factory = connection_factory
        self._now_string = now_string
        self._timestamp_factory = timestamp_factory
        self._legacy_labels_factory = legacy_labels_factory
        self._unhide_conversation = unhide_conversation

    @staticmethod
    def decode_json(value, fallback):
        """저장된 JSON 문자열을 읽는다. 옛 데이터가 깨져 있어도 화면 렌더링이 멈추지 않게 fallback을 돌려준다."""
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    def toggle_reaction(self, message_id: int, user_id: int, emoji: str) -> tuple[int, list]:
        """메시지에 이모지 반응을 추가하거나, 이미 있으면 제거한다.

        Returns:
            (대화방 ID, 갱신된 반응 목록).
        """
        # 이모지 하나가 여러 코드포인트일 수 있어 길이 상한은 넉넉하게 32자로 둔다.
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
            # DB 값이 예상과 다른 형태여도 새 목록으로 시작해 오류를 막는다.
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
        """메시지 고정 상태를 반전한다.

        대화방에는 고정 메시지를 하나만 둘 수 있어서, 새로 고정할 때 기존 고정은 모두 푼다.

        Returns:
            (대화방 ID, 이번 처리 뒤 고정됐는지 여부).
        """
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
            # 이미 고정된 메시지를 다시 누르면 해제, 아니면 새로 고정한다.
            now_pinned = not bool(message["pinned"])
            conn.execute(
                "UPDATE messages SET pinned = FALSE WHERE conversation_id = %s",
                (conversation_id,),
            )
            # 먼저 대화방의 모든 고정을 푼 뒤, 새로 고정할 때만 이 메시지에 다시 건다.
            if now_pinned:
                conn.execute("UPDATE messages SET pinned = TRUE WHERE id = %s", (message_id,))
            conn.commit()
        return conversation_id, now_pinned

    def edit_message(self, message_id: int, user_id: int, text: str) -> int:
        """작성자 본인의 메시지 본문을 수정한다.

        Returns:
            메시지가 속한 대화방 ID. 호출자가 실시간 갱신을 보낼 때 쓴다.
        """
        if not text:
            raise MessageServiceError("메시지 내용을 입력해주세요.")
        # 메시지 길이 상한. 프런트 입력창과 같은 값을 유지한다.
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
        """작성자 본인의 메시지를 삭제한다.

        Returns:
            (대화방 ID, 첨부 이미지 경로 또는 None). 이미지 파일 정리는 호출자가 이어서 한다.
        """
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
        """다른 사람의 메시지를 신고한다. 사유와 상세 내용의 길이를 검증한다.

        같은 사용자가 같은 메시지를 중복 신고해도 한 건만 저장된다.
        """
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
            # 자기 메시지는 신고 대상이 아니다.
            if message["sender_id"] == reporter_id:
                raise MessageServiceError("내 메시지는 신고할 수 없습니다.")
            conn.execute(
                """INSERT INTO reports (reporter_id, message_id, reason, detail, created_at)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (reporter_id, message_id) DO NOTHING""",
                (reporter_id, message_id, reason, detail or None, self._now_string()),
            )
            conn.commit()

    def forward_message(self, message_id: int, user_id: int, target_conversation_id: int) -> int:
        """접근할 수 있는 메시지를 내가 참여 중인 다른 대화방으로 복사해 보낸다.

        Returns:
            메시지를 받은 대화방 ID.
        """
        if not target_conversation_id:
            raise MessageServiceError("전달할 채팅방을 선택해주세요.")
        # 전달은 시간 생성·숨김 해제 콜백까지 모두 필요하므로, 하나라도 빠졌으면 설정 오류로 처리한다.
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
            # 기준 시각은 UTC 밀리초로 저장하고, 예전 time/date 컬럼에는 호환용 한국 시간 문자열을 함께 채운다.
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
            # 상대가 대화방을 숨겨 둔 상태여도 새 메시지가 오면 다시 보이게 한다.
            self._unhide_conversation(conn, target_conversation_id)
            conn.commit()
        return target_conversation_id

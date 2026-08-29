import json
import unittest

from services.message_service import MessageService, MessageServiceError


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self, message):
        self.message = message
        self.updated_reactions = None
        self.reset_pins_for = None
        self.pinned_message_id = None
        self.edited_text = None
        self.deleted_message_id = None
        self.report_params = None
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT messages.* FROM messages" in query:
            return Result(self.message)
        if "UPDATE messages SET reactions" in query:
            self.updated_reactions = json.loads(params[0])
        if "UPDATE messages SET pinned = FALSE" in query:
            self.reset_pins_for = params[0]
        if "UPDATE messages SET pinned = TRUE" in query:
            self.pinned_message_id = params[0]
        if "UPDATE messages SET text" in query:
            self.edited_text = params[0]
        if "DELETE FROM messages" in query:
            self.deleted_message_id = params[0]
        if "INSERT INTO reports" in query:
            self.report_params = params
        return Result(None)

    def commit(self):
        self.committed = True


class ForwardConnection:
    def __init__(self, *, source=True, target_member=True):
        self.source = source
        self.target_member = target_member
        self.insert_params = None
        self.last_read_params = None
        self.last_activity_params = None
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT messages.* FROM messages" in query:
            source = {
                "text": "원본",
                "image": None,
                "video": None,
                "file_path": None,
                "file_name": None,
                "file_size": None,
            }
            return Result(source if self.source else None)
        if "SELECT 1 FROM conversation_members" in query:
            return Result({"exists": 1} if self.target_member else None)
        if "INSERT INTO messages" in query:
            self.insert_params = params
            return Result({"id": 21})
        if "SET last_read_message_id" in query:
            self.last_read_params = params
        if "SET last_activity_id" in query:
            self.last_activity_params = params
        return Result(None)

    def commit(self):
        self.committed = True


class MessageServiceTests(unittest.TestCase):
    def test_toggle_reaction_adds_then_removes_emoji(self):
        connection = Connection({"conversation_id": 8, "reactions": '["👍"]'})
        service = MessageService(lambda: connection)

        conversation_id, reactions = service.toggle_reaction(3, 4, "❤️")

        self.assertEqual(conversation_id, 8)
        self.assertEqual(reactions, ["👍", "❤️"])
        self.assertEqual(connection.updated_reactions, ["👍", "❤️"])
        self.assertTrue(connection.committed)

    def test_toggle_reaction_rejects_invalid_emoji_without_db_access(self):
        service = MessageService(lambda: self.fail("DB 연결이 호출되면 안 됩니다."))

        with self.assertRaisesRegex(MessageServiceError, "올바른 반응"):
            service.toggle_reaction(3, 4, "")

    def test_toggle_reaction_rejects_missing_message(self):
        connection = Connection(None)
        service = MessageService(lambda: connection)

        with self.assertRaisesRegex(MessageServiceError, "메시지를 찾을 수 없습니다"):
            service.toggle_reaction(3, 4, "👍")

        self.assertFalse(connection.committed)

    def test_toggle_pin_replaces_existing_pin_in_conversation(self):
        connection = Connection({"conversation_id": 8, "pinned": False})
        service = MessageService(lambda: connection)

        conversation_id, pinned = service.toggle_pin(3, 4)

        self.assertEqual((conversation_id, pinned), (8, True))
        self.assertEqual(connection.reset_pins_for, 8)
        self.assertEqual(connection.pinned_message_id, 3)
        self.assertTrue(connection.committed)

    def test_toggle_pin_unpins_currently_pinned_message(self):
        connection = Connection({"conversation_id": 8, "pinned": True})
        service = MessageService(lambda: connection)

        _, pinned = service.toggle_pin(3, 4)

        self.assertFalse(pinned)
        self.assertEqual(connection.reset_pins_for, 8)
        self.assertIsNone(connection.pinned_message_id)

    def test_edit_message_updates_own_message(self):
        connection = Connection({"conversation_id": 8, "sender_id": 4})
        service = MessageService(lambda: connection)

        conversation_id = service.edit_message(3, 4, "수정한 내용")

        self.assertEqual(conversation_id, 8)
        self.assertEqual(connection.edited_text, "수정한 내용")
        self.assertTrue(connection.committed)

    def test_edit_message_rejects_another_users_message(self):
        connection = Connection({"conversation_id": 8, "sender_id": 9})
        service = MessageService(lambda: connection)

        with self.assertRaisesRegex(MessageServiceError, "본인 메시지만"):
            service.edit_message(3, 4, "수정 불가")

        self.assertIsNone(connection.edited_text)
        self.assertFalse(connection.committed)

    def test_delete_message_returns_image_path_after_deleting_own_message(self):
        connection = Connection(
            {"conversation_id": 8, "sender_id": 4, "image": "/static/uploads/photo.png"}
        )
        service = MessageService(lambda: connection)

        conversation_id, image_path = service.delete_message(3, 4)

        self.assertEqual((conversation_id, image_path), (8, "/static/uploads/photo.png"))
        self.assertEqual(connection.deleted_message_id, 3)
        self.assertTrue(connection.committed)

    def test_delete_message_rejects_another_users_message(self):
        connection = Connection({"conversation_id": 8, "sender_id": 9, "image": None})
        service = MessageService(lambda: connection)

        with self.assertRaisesRegex(MessageServiceError, "본인 메시지만 삭제"):
            service.delete_message(3, 4)

        self.assertIsNone(connection.deleted_message_id)
        self.assertFalse(connection.committed)

    def test_report_message_records_other_users_message(self):
        connection = Connection({"conversation_id": 8, "sender_id": 9})
        service = MessageService(lambda: connection, lambda: "2026-08-26 12:00:00")

        service.report_message(3, 4, "스팸", "반복 광고")

        self.assertEqual(
            connection.report_params, (4, 3, "스팸", "반복 광고", "2026-08-26 12:00:00")
        )
        self.assertTrue(connection.committed)

    def test_report_message_rejects_own_message(self):
        connection = Connection({"conversation_id": 8, "sender_id": 4})
        service = MessageService(lambda: connection, lambda: "2026-08-26 12:00:00")

        with self.assertRaisesRegex(MessageServiceError, "내 메시지"):
            service.report_message(3, 4, "스팸", "")

        self.assertIsNone(connection.report_params)
        self.assertFalse(connection.committed)

    def test_forward_message_copies_message_and_updates_target_state(self):
        connection = ForwardConnection()
        unhidden = []
        service = MessageService(
            lambda: connection,
            timestamp_factory=lambda: 123,
            legacy_labels_factory=lambda _timestamp: ("오전 1:00", "2026.08.26"),
            unhide_conversation=lambda _conn, conversation_id: unhidden.append(conversation_id),
        )

        conversation_id = service.forward_message(3, 4, 8)

        self.assertEqual(conversation_id, 8)
        self.assertEqual(connection.insert_params[0:3], (8, 4, "원본"))
        self.assertEqual(connection.last_read_params, (21, 8, 4))
        self.assertEqual(connection.last_activity_params, (21, 8))
        self.assertEqual(unhidden, [8])
        self.assertTrue(connection.committed)

    def test_forward_message_rejects_unknown_target(self):
        connection = ForwardConnection(target_member=False)
        service = MessageService(
            lambda: connection,
            timestamp_factory=lambda: 123,
            legacy_labels_factory=lambda _timestamp: ("", ""),
            unhide_conversation=lambda *_: None,
        )

        with self.assertRaisesRegex(MessageServiceError, "메시지 또는 채팅방"):
            service.forward_message(3, 4, 8)

        self.assertFalse(connection.committed)


if __name__ == "__main__":
    unittest.main()

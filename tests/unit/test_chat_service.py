import unittest

from services.chat_service import ChatService, ChatServiceError


class Result:
    def __init__(self, row, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, member=True, latest_id=7):
        self.member = member
        self.latest_id = latest_id
        self.committed = False
        self.update_params = None
        self.preference_updates = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT 1 FROM conversation_members" in query:
            return Result({"exists": 1} if self.member else None)
        if "SELECT MAX(id)" in query:
            return Result({"max_id": self.latest_id})
        if "UPDATE conversation_members" in query:
            self.update_params = params
            self.preference_updates.append((query, params))
        return Result(None)

    def commit(self):
        self.committed = True


class MembershipConnection:
    def __init__(
        self,
        *,
        actor_is_member=True,
        is_group=True,
        owner_id=1,
        is_disabled=False,
        existing_member_ids=None,
        users=None,
    ):
        self.actor_is_member = actor_is_member
        self.is_group = is_group
        self.owner_id = owner_id
        self.is_disabled = is_disabled
        self.existing_member_ids = set(existing_member_ids or {owner_id})
        self.users = users or {}
        self.inserted_member_ids = []
        self.deleted_member_ids = []
        self.renamed_to = None
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT is_group, is_disabled" in query:
            return Result({"is_group": self.is_group, "is_disabled": self.is_disabled})
        if "SELECT is_group, owner_id, is_disabled" in query:
            return Result(
                {
                    "is_group": self.is_group,
                    "owner_id": self.owner_id,
                    "is_disabled": self.is_disabled,
                }
            )
        if "SELECT id FROM users" in query:
            username = params[0]
            user_id = self.users.get(username)
            return Result({"id": user_id} if user_id is not None else None)
        if "SELECT 1 FROM conversation_members" in query:
            user_id = params[1]
            is_member = (
                self.actor_is_member
                if user_id == self.owner_id
                else user_id in self.existing_member_ids
            )
            return Result({"exists": 1} if is_member else None)
        if "INSERT INTO conversation_members" in query:
            self.inserted_member_ids.append(params[1])
        if "DELETE FROM conversation_members" in query:
            self.deleted_member_ids.append(params[1])
        if "UPDATE conversations SET name" in query:
            self.renamed_to = params[0]
        return Result(None)

    def commit(self):
        self.committed = True


class LeaveConnection:
    def __init__(self, *, member=True, remaining=1, image_paths=None):
        self.member = member
        self.remaining = remaining
        self.image_paths = image_paths or []
        self.deleted_member = False
        self.new_owner_id = None
        self.deleted_conversation = False
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT 1 FROM conversation_members" in query:
            return Result({"exists": 1} if self.member else None)
        if "SELECT owner_id, is_group" in query:
            return Result({"owner_id": 1, "is_group": True})
        if "SELECT display_name, username" in query:
            return Result({"display_name": "방장", "username": "owner"})
        if "DELETE FROM conversation_members" in query:
            self.deleted_member = True
        if "ORDER BY joined_at" in query:
            return Result({"user_id": 2} if self.remaining else None)
        if "UPDATE conversations SET owner_id" in query:
            self.new_owner_id = params[0]
        if "SELECT COUNT(*) AS cnt" in query:
            return Result({"cnt": self.remaining})
        if "SELECT image FROM messages" in query:
            return Result(None, [{"image": image_path} for image_path in self.image_paths])
        if "DELETE FROM conversations" in query:
            self.deleted_conversation = True
        return Result(None)

    def commit(self):
        self.committed = True


class DisableConnection:
    def __init__(self, *, member=True, owner_id=1, is_disabled=False):
        self.member = member
        self.owner_id = owner_id
        self.is_disabled = is_disabled
        self.disabled_by = None
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT is_group, owner_id, is_disabled" in query:
            return Result(
                {"is_group": True, "owner_id": self.owner_id, "is_disabled": self.is_disabled}
            )
        if "SELECT 1 FROM conversation_members" in query:
            return Result({"exists": 1} if self.member else None)
        if "SELECT display_name, username" in query:
            return Result({"display_name": "방장", "username": "owner"})
        if "UPDATE conversations SET is_disabled" in query:
            self.disabled_by = params[0]
        return Result(None)

    def commit(self):
        self.committed = True


class ThemeConnection:
    def __init__(self, *, member=True, is_disabled=False):
        self.member = member
        self.is_disabled = is_disabled
        self.theme = None
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params=()):
        if "SELECT 1 FROM conversation_members" in query:
            return Result({"exists": 1} if self.member else None)
        if "SELECT is_disabled FROM conversations" in query:
            return Result({"is_disabled": self.is_disabled})
        if "SELECT display_name, username" in query:
            return Result({"display_name": "사용자", "username": "user"})
        if "UPDATE conversations SET chat_theme" in query:
            self.theme = params[0]
        return Result(None)

    def commit(self):
        self.committed = True


class ChatServiceTests(unittest.TestCase):
    def test_mark_read_updates_to_the_latest_message(self):
        connection = Connection(latest_id=14)

        self.assertTrue(ChatService(lambda: connection).mark_read(3, 4))
        self.assertEqual(connection.update_params, (14, 3, 4))
        self.assertTrue(connection.committed)

    def test_mark_read_rejects_non_members_without_writing(self):
        connection = Connection(member=False)

        self.assertFalse(ChatService(lambda: connection).mark_read(3, 4))
        self.assertIsNone(connection.update_params)
        self.assertFalse(connection.committed)

    def test_create_group_requires_a_name(self):
        service = ChatService(lambda: self.fail("DB 연결이 호출되면 안 됩니다."))

        with self.assertRaisesRegex(ChatServiceError, "방 이름"):
            service.create_group(1, "", [])

    def test_update_preferences_changes_only_requested_values(self):
        connection = Connection()

        self.assertTrue(ChatService(lambda: connection).update_preferences(3, 4, is_muted=True))

        self.assertEqual(len(connection.preference_updates), 1)
        self.assertEqual(connection.preference_updates[0][1], (True, 3, 4))
        self.assertTrue(connection.committed)

    def test_update_preferences_rejects_empty_request(self):
        service = ChatService(lambda: self.fail("DB 연결이 호출되면 안 됩니다."))

        with self.assertRaisesRegex(ChatServiceError, "변경할 설정"):
            service.update_preferences(3, 4)

    def test_rename_group_changes_name_for_owner(self):
        connection = MembershipConnection(owner_id=1)
        service = ChatService(lambda: connection)

        service.rename_group(8, 1, "프로젝트 대화방")

        self.assertEqual(connection.renamed_to, "프로젝트 대화방")
        self.assertTrue(connection.committed)

    def test_rename_group_rejects_non_owner(self):
        connection = MembershipConnection(owner_id=2, existing_member_ids={1, 2})
        service = ChatService(lambda: connection)

        with self.assertRaisesRegex(ChatServiceError, "방장만"):
            service.rename_group(8, 1, "변경 불가")

        self.assertIsNone(connection.renamed_to)
        self.assertFalse(connection.committed)

    def test_hide_conversation_marks_only_member_copy_as_hidden(self):
        connection = Connection()
        service = ChatService(lambda: connection, lambda: "2026-08-26 12:00:00")

        self.assertTrue(service.hide_conversation(3, 4))

        self.assertEqual(connection.update_params, ("2026-08-26 12:00:00", 3, 4))
        self.assertTrue(connection.committed)

    def test_hide_conversation_rejects_non_members(self):
        connection = Connection(member=False)
        service = ChatService(lambda: connection, lambda: "2026-08-26 12:00:00")

        self.assertFalse(service.hide_conversation(3, 4))
        self.assertIsNone(connection.update_params)
        self.assertFalse(connection.committed)

    def test_leave_conversation_transfers_group_ownership(self):
        connection = LeaveConnection(remaining=1)
        messages = []
        service = ChatService(lambda: connection)

        result = service.leave_conversation(
            8, 1, lambda _conn, _id, name, actor_id: messages.append((name, actor_id))
        )

        self.assertFalse(result.conversation_deleted)
        self.assertTrue(connection.deleted_member)
        self.assertEqual(connection.new_owner_id, 2)
        self.assertEqual(messages, [("방장", 1)])
        self.assertTrue(connection.committed)

    def test_leave_conversation_deletes_empty_room_and_returns_images(self):
        connection = LeaveConnection(remaining=0, image_paths=["/static/uploads/a.png"])
        service = ChatService(lambda: connection)

        result = service.leave_conversation(8, 1, lambda *_: None)

        self.assertTrue(result.conversation_deleted)
        self.assertEqual(result.image_paths, ["/static/uploads/a.png"])
        self.assertTrue(connection.deleted_conversation)
        self.assertTrue(connection.committed)

    def test_leave_conversation_rejects_non_members(self):
        connection = LeaveConnection(member=False)
        service = ChatService(lambda: connection)

        with self.assertRaisesRegex(ChatServiceError, "대화방을 찾을 수 없습니다"):
            service.leave_conversation(8, 1, lambda *_: None)

        self.assertFalse(connection.committed)

    def test_disable_group_marks_group_disabled_and_records_actor(self):
        connection = DisableConnection()
        messages = []
        service = ChatService(lambda: connection)

        service.disable_group(
            8, 1, lambda _conn, _id, name, actor_id: messages.append((name, actor_id))
        )

        self.assertEqual(connection.disabled_by, 1)
        self.assertEqual(messages, [("방장", 1)])
        self.assertTrue(connection.committed)

    def test_disable_group_rejects_non_owner(self):
        connection = DisableConnection(owner_id=2)
        service = ChatService(lambda: connection)

        with self.assertRaisesRegex(ChatServiceError, "그룹 방장만"):
            service.disable_group(8, 1, lambda *_: None)

        self.assertIsNone(connection.disabled_by)
        self.assertFalse(connection.committed)

    def test_update_theme_updates_active_conversation_and_records_actor(self):
        connection = ThemeConnection()
        messages = []
        service = ChatService(lambda: connection)

        service.update_theme(
            8, 1, "aurora", lambda _conn, _id, name, actor_id: messages.append((name, actor_id))
        )

        self.assertEqual(connection.theme, "aurora")
        self.assertEqual(messages, [("사용자", 1)])
        self.assertTrue(connection.committed)

    def test_update_theme_rejects_invalid_theme_without_db_access(self):
        service = ChatService(lambda: self.fail("DB 연결이 호출되면 안 됩니다."))

        with self.assertRaisesRegex(ChatServiceError, "지원하지 않는"):
            service.update_theme(8, 1, "unsupported", lambda *_: None)

    def test_update_theme_rejects_disabled_conversation(self):
        connection = ThemeConnection(is_disabled=True)
        service = ChatService(lambda: connection)

        with self.assertRaisesRegex(ChatServiceError, "종료된"):
            service.update_theme(8, 1, "aurora", lambda *_: None)

        self.assertIsNone(connection.theme)
        self.assertFalse(connection.committed)

    def test_invite_members_adds_only_new_users(self):
        connection = MembershipConnection(
            existing_member_ids={1, 2}, users={"existing": 2, "new": 3}
        )
        service = ChatService(lambda: connection, lambda: "2026-08-26 12:00:00")

        service.invite_members(8, 1, ["existing", "new"])

        self.assertEqual(connection.inserted_member_ids, [3])
        self.assertTrue(connection.committed)

    def test_invite_members_rejects_disabled_group(self):
        connection = MembershipConnection(is_disabled=True)
        service = ChatService(lambda: connection, lambda: "2026-08-26 12:00:00")

        with self.assertRaisesRegex(ChatServiceError, "종료된"):
            service.invite_members(8, 1, ["new"])

        self.assertFalse(connection.committed)

    def test_remove_member_deletes_member_for_group_owner(self):
        connection = MembershipConnection(existing_member_ids={1, 2})
        service = ChatService(lambda: connection)

        service.remove_member(8, 1, 2)

        self.assertEqual(connection.deleted_member_ids, [2])
        self.assertTrue(connection.committed)

    def test_remove_member_rejects_non_owner(self):
        connection = MembershipConnection(owner_id=2, existing_member_ids={1, 2})
        service = ChatService(lambda: connection)

        with self.assertRaisesRegex(ChatServiceError, "방장만"):
            service.remove_member(8, 1, 2)

        self.assertEqual(connection.deleted_member_ids, [])
        self.assertFalse(connection.committed)


if __name__ == "__main__":
    unittest.main()

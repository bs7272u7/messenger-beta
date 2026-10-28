"""ChatService 단위 테스트. 서비스가 실행하는 SQL을 흉내 내는 가짜 연결(Connection 계열)로 DB 없이 동작을 확인한다.

가짜 연결은 쿼리 문자열에 포함된 키워드로 응답을 고르고, 서비스가 실제로 실행한 쓰기(INSERT/UPDATE/DELETE) 파라미터를 속성에 기록한다.
테스트는 그 기록과 commit 여부로 결과를 검증한다.
"""

import unittest

from services.chat_service import ChatService, ChatServiceError


class Result:
    """fetchone/fetchall만 흉내 내는 쿼리 결과."""

    def __init__(self, row, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Connection:
    """읽음 처리·환경설정 테스트용 가짜 연결. member로 대화방 멤버 여부를, latest_id로 마지막 메시지 ID를 정한다."""

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
        # '삭제(숨김)' UPDATE는 안에 SELECT MAX(id)를 품고 있으므로 UPDATE를 먼저 판별한다.
        if "UPDATE conversation_members" in query:
            self.update_params = params
            self.preference_updates.append((query, params))
            return Result(None)
        if "SELECT MAX(id)" in query:
            return Result({"max_id": self.latest_id})
        return Result(None)

    def commit(self):
        self.committed = True


class MembershipConnection:
    """그룹 만들기·이름 변경·초대·강퇴 테스트용 가짜 연결. 요청자의 멤버/방장 여부, 그룹·비활성 상태, 기존 멤버 ID를 설정하고 추가·삭제된 멤버와 바뀐 이름을 기록한다."""

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
    """대화방 나가기 테스트용 가짜 연결. 남은 멤버 수(remaining)와 방에 남은 이미지 경로를 설정하고, 방장 위임·방 삭제 여부를 기록한다."""

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
    """그룹 비활성화(해산) 테스트용 가짜 연결. 방장 ID와 현재 비활성 여부를 설정하고, 누가 비활성화했는지 기록한다."""

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
    """채팅 테마 변경 테스트용 가짜 연결. 멤버 여부와 비활성 여부를 설정하고, 저장된 테마를 기록한다."""

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
    """대화방 권한 규칙을 확인한다: 멤버만 읽음·숨김·나가기·테마 변경이 가능하고, 이름 변경·비활성화·강퇴는 방장만 가능하며, 비활성 그룹에는 초대·테마 변경을 할 수 없다."""

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

        # (숨긴 시각, 지울 기준을 구하는 대화방 번호, 대화방 번호, 사용자 번호). 숨기면서 그때까지의 기록도 내게서 지운다.
        self.assertEqual(connection.update_params, ("2026-08-26 12:00:00", 3, 3, 4))
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

"""AdminService의 입력 정규화·검증 규칙 단위 테스트(DB 없이 정적 메서드만 사용)."""

import unittest

from services.admin_service import AdminService, AdminServiceError


class AdminServiceTests(unittest.TestCase):
    """관리자 API로 들어온 선택 목록, 제재 요청, 공지 내용이 서버에서 올바르게 정리·거부되는지 확인한다."""

    def test_selected_ids_removes_duplicates_and_non_positive_values(self):
        """선택 삭제 목록: 문자열 숫자는 정수로 바꾸고, 중복과 0 이하 값은 버린다."""
        self.assertEqual(set(AdminService.selected_ids([1, "2", 1, 0, -3], "문의")), {1, 2})

    def test_selected_ids_rejects_empty_selection(self):
        """아무것도 선택하지 않고 삭제를 요청하면 거부한다."""
        with self.assertRaisesRegex(AdminServiceError, "삭제할 문의"):
            AdminService.selected_ids([], "문의")

    def test_selected_ids_rejects_invalid_selection(self):
        """숫자로 바꿀 수 없는 값이 섞여 있으면 거부한다."""
        with self.assertRaisesRegex(AdminServiceError, "선택 정보"):
            AdminService.selected_ids(["invalid"], "리뷰")

    def test_moderation_request_normalizes_values(self):
        """처리 사유의 앞뒤 공백을 지우고, 문자열로 온 신고 ID를 정수로 바꾼다."""
        self.assertEqual(
            AdminService.moderation_request("24h", "3", " 사유 "),
            ("24h", 3, "사유"),
        )

    def test_moderation_request_rejects_unsupported_action(self):
        """AdminService.MODERATION_ACTIONS에 없는 처리 방식이면 거부한다."""
        with self.assertRaisesRegex(AdminServiceError, "지원하지 않는"):
            AdminService.moderation_request("delete", None, "")

    def test_notice_content_rejects_length_over_limit(self):
        """공지 내용은 5000자를 넘을 수 없다."""
        with self.assertRaisesRegex(AdminServiceError, "공지사항 길이"):
            AdminService.notice_content("제목", "a" * 5001)


if __name__ == "__main__":
    unittest.main()

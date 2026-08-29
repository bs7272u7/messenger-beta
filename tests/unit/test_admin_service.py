import unittest

from services.admin_service import AdminService, AdminServiceError


class AdminServiceTests(unittest.TestCase):
    def test_selected_ids_removes_duplicates_and_non_positive_values(self):
        self.assertEqual(set(AdminService.selected_ids([1, "2", 1, 0, -3], "문의")), {1, 2})

    def test_selected_ids_rejects_empty_selection(self):
        with self.assertRaisesRegex(AdminServiceError, "삭제할 문의"):
            AdminService.selected_ids([], "문의")

    def test_selected_ids_rejects_invalid_selection(self):
        with self.assertRaisesRegex(AdminServiceError, "선택 정보"):
            AdminService.selected_ids(["invalid"], "리뷰")

    def test_moderation_request_normalizes_values(self):
        self.assertEqual(
            AdminService.moderation_request("24h", "3", " 사유 "),
            ("24h", 3, "사유"),
        )

    def test_moderation_request_rejects_unsupported_action(self):
        with self.assertRaisesRegex(AdminServiceError, "지원하지 않는"):
            AdminService.moderation_request("delete", None, "")

    def test_notice_content_rejects_length_over_limit(self):
        with self.assertRaisesRegex(AdminServiceError, "공지사항 길이"):
            AdminService.notice_content("제목", "a" * 5001)


if __name__ == "__main__":
    unittest.main()

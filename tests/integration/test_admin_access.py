"""관리자 페이지·API 접근 통제 통합 테스트."""

import unittest

import app as application_module


class AdminAccessTests(unittest.TestCase):
    """권한이 없는 요청에는 관리자 경로의 존재 자체를 숨기고(404), 라우트가 중복 등록되지 않았는지 확인한다."""

    def setUp(self):
        self.client = application_module.app.test_client()

    def test_admin_page_is_not_exposed_to_anonymous_users(self):
        """로그인하지 않은 사용자에게 /admin은 404를 돌려준다(403이 아니라 404라서 경로 존재를 알려 주지 않는다)."""
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 404)

    def test_admin_api_is_not_exposed_to_anonymous_users(self):
        """관리자 API도 같은 방식으로 404 + success:false를 돌려준다."""
        response = self.client.get("/api/admin/users")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["success"])

    def test_admin_blueprint_does_not_register_duplicate_urls(self):
        """같은 (경로, 메서드) 조합이 두 번 등록되면 어느 함수가 응답할지 모호하므로 중복이 없어야 한다."""
        routes = [
            (rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})))
            for rule in application_module.app.url_map.iter_rules()
            if rule.endpoint.startswith("admin.")
        ]

        self.assertEqual(len(routes), len(set(routes)))


if __name__ == "__main__":
    unittest.main()

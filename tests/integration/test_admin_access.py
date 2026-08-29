import unittest

import app as application_module


class AdminAccessTests(unittest.TestCase):
    def setUp(self):
        self.client = application_module.app.test_client()

    def test_admin_page_is_not_exposed_to_anonymous_users(self):
        response = self.client.get("/admin")

        self.assertEqual(response.status_code, 404)

    def test_admin_api_is_not_exposed_to_anonymous_users(self):
        response = self.client.get("/api/admin/users")

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["success"])

    def test_admin_blueprint_does_not_register_duplicate_urls(self):
        routes = [
            (rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"})))
            for rule in application_module.app.url_map.iter_rules()
            if rule.endpoint.startswith("admin.")
        ]

        self.assertEqual(len(routes), len(set(routes)))


if __name__ == "__main__":
    unittest.main()

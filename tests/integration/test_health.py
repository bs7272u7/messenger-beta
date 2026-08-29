import unittest

import app as application_module


class HealthCheckTests(unittest.TestCase):
    def test_health_check_reports_a_machine_readable_status(self):
        client = application_module.app.test_client()

        response = client.get("/healthz")

        self.assertIn(response.status_code, {200, 503})
        payload = response.get_json()
        self.assertIn(payload["status"], {"ok", "degraded"})
        self.assertIn(payload["database"], {"available", "unavailable"})

    def test_landing_page_is_available_without_login(self):
        client = application_module.app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Cloud Chatting", response.data)

    def test_login_page_supports_register_mode_link(self):
        client = application_module.app.test_client()

        response = client.get("/login?mode=register")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"password-confirmation", response.data)
        self.assertIn(b"requestMode", response.data)


if __name__ == "__main__":
    unittest.main()

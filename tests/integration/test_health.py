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

        register_response = client.get("/login?mode=register")
        login_response = client.get("/login")

        self.assertEqual(register_response.status_code, 200)
        self.assertEqual(login_response.status_code, 200)
        self.assertIn(b"password-confirmation", register_response.data)

        register_page = register_response.get_data(as_text=True)
        login_page = login_response.get_data(as_text=True)
        self.assertIn('data-auth-mode="register"', register_page)
        self.assertIn("Cloud Chatting 계정을 만들고 대화를 시작하세요.", register_page)
        self.assertIn('data-auth-mode="login"', login_page)
        self.assertIn("계정으로 로그인해서 대화를 이어가세요.", login_page)


if __name__ == "__main__":
    unittest.main()

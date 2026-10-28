"""공개 페이지와 헬스 체크 통합 테스트(Flask 테스트 클라이언트 사용, 실제 DB는 필요하지 않다)."""

import unittest
from unittest import mock

import app as application_module


class HealthCheckTests(unittest.TestCase):
    """로그인하지 않은 방문자와 로그인한 사용자가 각각 어떤 화면을 받는지, /healthz가 기계가 읽을 수 있는 상태를 돌려주는지 확인한다."""

    def test_health_check_reports_a_machine_readable_status(self):
        """DB가 없어도 200 또는 503과 정해진 상태 값을 돌려줘야 한다(배포 환경의 상태 점검용)."""
        client = application_module.app.test_client()

        response = client.get("/healthz")

        self.assertIn(response.status_code, {200, 503})
        payload = response.get_json()
        self.assertIn(payload["status"], {"ok", "degraded"})
        self.assertIn(payload["database"], {"available", "unavailable"})

    def test_root_serves_the_combined_intro_and_login_screen_to_signed_out_visitors(self):
        """로그아웃 상태의 '/'는 왼쪽 로고와 오른쪽 로그인 폼이 함께 있는 통합 화면을 보여 준다."""
        client = application_module.app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        # 소개(로고) 영역과 로그인 폼이 한 화면에 있어야 한다.
        self.assertIn('class="intro-brand"', page)
        self.assertIn('id="auth-form"', page)
        # 처음에는 로그인 모드이고, 같은 자리에서 회원가입으로 전환할 수 있다.
        self.assertIn('data-auth-mode="login"', page)
        self.assertIn('id="switch-link"', page)
        # 약관 링크는 하단 링크 줄에 있다.
        self.assertIn('href="/terms"', page)
        self.assertIn('href="/privacy"', page)

    def test_root_redirects_signed_in_users_to_the_chat_screen(self):
        """로그인된 세션이면 '/'는 메신저 화면(/chat)으로 보낸다."""
        client = application_module.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = 1
            session["session_token"] = "token"

        # DB 없이 실행하므로 계정 토큰 확인은 통과한 것으로 둔다.
        with mock.patch.object(application_module, "session_token_matches", return_value=True):
            response = client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/chat"))

    def test_session_without_account_token_is_treated_as_signed_out(self):
        """계정 토큰이 없는 예전 세션(예: DB 초기화 전 쿠키)은 로그아웃 상태로 처리된다."""
        client = application_module.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = 1

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("편안하게", response.get_data(as_text=True))
        with client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_session_with_mismatched_account_token_is_cleared(self):
        """세션의 계정 토큰이 DB 값과 다르면 API는 로그인이 필요하다고 응답한다."""
        client = application_module.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = 1
            session["session_token"] = "old-token"

        with mock.patch.object(application_module, "session_token_matches", return_value=False):
            response = client.get("/api/conversations")

        self.assertEqual(response.status_code, 401)

    def test_chat_template_has_the_ui_layout_setting_and_loads_modern_styles(self):
        """메신저 화면 템플릿에 UI 선택(클래식/모던) 항목과 모던 전용 스타일 파일이 들어 있다.

        /chat은 로그인과 DB가 필요하므로, 템플릿만 직접 렌더링해 확인한다.
        """
        with application_module.app.test_request_context("/chat"):
            page = application_module.render_template(
                "index.html",
                user_id=1,
                username="tester",
                profile_image=None,
                user_email="tester@example.com",
                user_language="ko",
                csrf_token="token",
                initial_profile="bobby",
            )

        self.assertIn('id="ui-layout-select"', page)
        # /u/<아이디>로 들어오면 그 아이디가 스크립트에 전달된다.
        self.assertIn('INITIAL_PROFILE_USERNAME = "bobby"', page)
        self.assertIn('<option value="classic">', page)
        self.assertIn('<option value="modern">', page)
        self.assertIn("css/ui-modern.css", page)
        # 화면이 그려지기 전에 저장된 UI 방식을 <html>에 먼저 적용하는 스크립트가 head에 있어야 한다.
        self.assertIn('localStorage.getItem("uiLayout")', page)
        # 모던 프로필 화면과 팔로워/팔로잉 목록 팝업, 그리고 그것을 그리는 스크립트가 들어 있어야 한다.
        self.assertIn('id="modern-profile-page"', page)
        self.assertIn('id="modern-relations-overlay"', page)
        self.assertIn("js/modern-profile.js", page)
        self.assertIn('id="modern-search-page"', page)
        self.assertIn('id="modern-inbox-overlay"', page)
        self.assertIn("js/modern-inbox.js", page)

    def test_login_page_supports_register_mode_link(self):
        """/login?mode=register는 회원가입 모드로, /login은 로그인 모드로 렌더링된다."""
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

"""로그인·로그아웃·회원가입 API를 세션 처리와 함께 제공합니다."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from flask import Blueprint, current_app, jsonify, request, session
from flask_login import login_user, logout_user

from services.auth_service import AuthService
from services.password_policy import PasswordPolicy
from services.registration_service import RegistrationError, RegistrationService


def create_auth_blueprint(
    auth_service: AuthService,
    registration_service: RegistrationService,
    connection_factory: Callable[[], Any],
    user_loader: Callable[[str], Any | None],
    suspension_state_getter: Callable[[dict[str, Any]], str | None],
    supported_languages: set[str],
    login_rate_limit,
    client_ip_getter: Callable[[], str],
    api_login_required,
    register_rate_limit,
    register_user_loader: Callable[[str], Any | None],
) -> Blueprint:
    """인증 서비스와 보안 보조 함수를 주입해 인증 라우트를 만듭니다."""
    auth_bp = Blueprint("auth", __name__)

    @auth_bp.route("/api/login", methods=["POST"])
    @login_rate_limit
    def login():
        """자격 증명을 검증하고, 정지 상태를 확인한 뒤 새 로그인 세션을 만듭니다."""
        data = request.get_json() or {}
        identifier = (data.get("identifier") or "").strip()
        password = data.get("password") or ""
        requested_language = (
            data.get("language") if data.get("language") in supported_languages else None
        )

        user = auth_service.authenticate(identifier, password)

        if user is None:
            current_app.logger.warning(
                "Failed login attempt: ip=%s",
                client_ip_getter(),
            )
            return jsonify(
                {
                    "success": False,
                    "error": "아이디/이메일 또는 비밀번호가 올바르지 않습니다.",
                }
            )

        suspension_state = suspension_state_getter(user)

        if suspension_state == "expired":
            with connection_factory() as conn:
                conn.execute(
                    """
                    UPDATE users
                    SET is_suspended = FALSE,
                        suspended_until = 0,
                        suspension_reason = NULL
                    WHERE id = %s
                    """,
                    (user["id"],),
                )

                conn.commit()
        elif suspension_state:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "이용 정지 상태인 계정입니다. 고객센터로 문의해주세요.",
                    }
                ),
                403,
            )

        # 이전 계정의 세션 키가 남지 않도록 로그인 성공 직전에 모두 비웁니다.
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["display_name"] = user["display_name"] or user["username"]
        session["profile_image"] = user["profile_image"]
        session["language"] = requested_language or (
            user["language"] if user["language"] in supported_languages else "ko"
        )

        if requested_language:
            with connection_factory() as conn:
                conn.execute(
                    "UPDATE users SET language = %s WHERE id = %s",
                    (requested_language, user["id"]),
                )
                conn.commit()

        login_user_data = user_loader(str(user["id"]))
        if login_user_data is None:
            session.clear()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "로그인 정보를 불러오지 못했습니다.",
                    }
                ),
                500,
            )

        login_user(login_user_data, fresh=True)
        return jsonify({"success": True})

    @auth_bp.route("/api/logout", methods=["POST"])
    @api_login_required
    def logout():
        """Flask-Login과 Flask 세션을 함께 종료합니다."""
        logout_user()
        session.clear()
        return jsonify({"success": True})

    @auth_bp.route("/api/register", methods=["POST"])
    @register_rate_limit
    def register():
        """입력 규칙·이메일 인증 코드를 확인한 뒤 가입과 자동 로그인을 처리합니다."""
        data = request.get_json() or {}
        password = data.get("password") or ""
        password_confirmation = (
            data.get("password_confirmation") or data.get("password_confirm") or ""
        )
        language = data.get("language") if data.get("language") in supported_languages else "ko"
        display_name = (data.get("display_name") or "").strip()
        username = (data.get("username") or "").strip().lower()
        email = (data.get("email") or "").strip().lower()
        code = (data.get("code") or "").strip()

        if not username or not email or not password:
            return jsonify({"success": False, "error": "아이디, 이메일, 비밀번호를 입력해주세요."})
        if password_confirmation and password != password_confirmation:
            return jsonify({"success": False, "error": "비밀번호 확인이 일치하지 않습니다."}), 400
        if not re.fullmatch(r"[a-z0-9]{5,}", username):
            return jsonify(
                {"success": False, "error": "아이디는 영문 소문자와 숫자로 5자 이상 입력해주세요."}
            )
        if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."})
        if not PasswordPolicy.is_valid(password):
            return jsonify(
                {
                    "success": False,
                    "error": PasswordPolicy.error_message(),
                }
            )

        try:
            registered_user = registration_service.register(
                username=username,
                email=email,
                password=password,
                display_name=display_name,
                language=language,
                code=code,
            )
        except RegistrationError as error:
            return jsonify({"success": False, "error": str(error)})

        # 새 계정의 세션에 기존 사용자 정보가 섞이지 않게 초기화합니다.
        session.clear()
        session["user_id"] = registered_user.id
        session["username"] = registered_user.username
        session["display_name"] = registered_user.display_name
        session["profile_image"] = registered_user.profile_image
        session["language"] = registered_user.language

        new_user = register_user_loader(str(registered_user.id))
        if new_user is None:
            current_app.logger.error(
                "가입 직후 사용자를 불러오지 못했습니다: user_id=%s", registered_user.id
            )
            session.clear()
            return (
                jsonify({"success": False, "error": "계정 생성 후 로그인 처리에 실패했습니다."}),
                500,
            )

        login_user(new_user, fresh=True)
        return jsonify({"success": True})

    return auth_bp

"""로그인·로그아웃·회원가입 API를 세션 처리와 함께 제공한다."""

from __future__ import annotations

import re
import secrets
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
    """인증 서비스와 보안 보조 함수를 주입받아 인증 라우트를 만든다.

    Args:
        auth_service: 아이디·비밀번호를 검증하는 서비스.
        registration_service: 인증코드 확인과 계정 생성을 처리하는 서비스.
        connection_factory: DB 연결을 만들어 주는 함수.
        user_loader: 사용자 ID로 Flask-Login 사용자 객체를 만드는 함수.
        suspension_state_getter: 계정의 정지 상태(영구/기간/만료)를 판단하는 함수.
        supported_languages: 서버가 받아 주는 언어 코드 집합.
        login_rate_limit: 로그인 시도 횟수를 제한하는 데코레이터.
        client_ip_getter: 요청자의 IP를 돌려주는 함수. 실패 로그에 쓴다.
        api_login_required: 로그인 여부를 검사하는 데코레이터.
        register_rate_limit: 회원가입 시도 횟수를 제한하는 데코레이터.
        register_user_loader: 가입 직후 사용자 객체를 만드는 함수.
    """
    auth_bp = Blueprint("auth", __name__)

    def account_session_token(user_id: int) -> str:
        """계정 토큰을 돌려준다. 아직 없으면 새로 만들어 저장한다.

        이미 있는 토큰은 그대로 재사용하므로, 다른 기기에서 로그인해도 기존 기기의 로그인은 유지된다.
        토큰은 비밀번호를 바꾸거나 재설정할 때만 바뀐다(app.py의 drop_stale_sessions 참고).
        """
        with connection_factory() as conn:
            row = conn.execute(
                "SELECT session_token FROM users WHERE id = %s", (user_id,)
            ).fetchone()
            if row and row["session_token"]:
                return row["session_token"]
            token = secrets.token_urlsafe(32)
            conn.execute("UPDATE users SET session_token = %s WHERE id = %s", (token, user_id))
            conn.commit()
        return token

    @auth_bp.route("/api/login", methods=["POST"])
    @login_rate_limit
    def login():
        """아이디(또는 이메일)와 비밀번호를 확인하고, 정지 상태를 점검한 뒤 로그인 세션을 만든다.

        기간 정지가 이미 끝난 계정은 이 시점에 자동으로 정지를 풀어 준다.
        """
        data = request.get_json() or {}
        identifier = (data.get("identifier") or "").strip()
        password = data.get("password") or ""
        requested_language = (
            data.get("language") if data.get("language") in supported_languages else None
        )

        # 계정이 없을 때와 비밀번호가 틀렸을 때 모두 None이 돌아온다. 같은 응답을 줘서 계정 존재 여부를 숨긴다.
        user = auth_service.authenticate(identifier, password)

        if user is None:
            # 비밀번호 대입 공격을 추적할 수 있게 실패 시도의 IP를 남긴다(계정 정보는 남기지 않는다).
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

        # 기간 정지가 끝난 계정은 정지 표시를 지우고 정상 로그인으로 이어 간다.
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
        # 영구·기간 정지 중이면 로그인을 막는다. 정지 사유는 로그인 화면에 노출하지 않는다.
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

        # 다른 계정으로 로그인했던 흔적(세션 키)이 남지 않도록 로그인 성공 직전에 전부 비운다.
        session.clear()
        session["user_id"] = user["id"]
        session["session_token"] = account_session_token(user["id"])
        session["username"] = user["username"]
        session["display_name"] = user["display_name"] or user["username"]
        session["profile_image"] = user["profile_image"]
        session["language"] = requested_language or (
            user["language"] if user["language"] in supported_languages else "ko"
        )

        # 로그인 화면에서 언어를 골랐다면 그 선택을 계정 설정으로도 저장한다.
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

        # fresh=True: 방금 비밀번호로 인증한 세션임을 표시한다(민감한 작업 재인증 판단에 쓴다).
        login_user(login_user_data, fresh=True)
        return jsonify({"success": True})

    @auth_bp.route("/api/logout", methods=["POST"])
    @api_login_required
    def logout():
        """Flask-Login 로그인 상태와 Flask 세션 값을 함께 지운다."""
        logout_user()
        session.clear()
        return jsonify({"success": True})

    @auth_bp.route("/api/register", methods=["POST"])
    @register_rate_limit
    def register():
        """입력값과 이메일 인증코드를 검증한 뒤 계정을 만들고 바로 로그인시킨다.

        아이디는 영문 소문자·숫자 5자 이상, 비밀번호는 PasswordPolicy를 따른다.
        """
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
        # 아이디는 입력창 안내와 같은 규칙(영문 소문자·숫자 5자 이상)으로 서버에서도 다시 검사한다.
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
            # 인증코드 확인, 중복 검사, 사용자 생성은 서비스에서 한 트랜잭션으로 처리한다.
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

        session.clear()
        session["user_id"] = registered_user.id
        session["session_token"] = account_session_token(registered_user.id)
        session["username"] = registered_user.username
        session["display_name"] = registered_user.display_name
        session["profile_image"] = registered_user.profile_image
        session["language"] = registered_user.language

        # 가입은 성공했는데 사용자 조회만 실패하는 비정상 상황은 로그로 남기고 세션을 비운다.
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

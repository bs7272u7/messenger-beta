"""프로필·표시 이름·언어처럼 계정 화면의 설정 API를 제공한다."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import Blueprint, jsonify, request, session


def create_profile_blueprint(
    connection_factory: Callable[[], Any],
    supported_languages: set[str],
    api_login_required,
    profile_update_recipient_ids,
    profile_updated_notifier,
) -> Blueprint:
    """DB 연결과 프로필 변경 알림 함수를 주입받아 계정 설정 라우트를 만든다.

    Args:
        supported_languages: 서버가 받아 주는 언어 코드 집합.
        profile_update_recipient_ids: 프로필이 바뀐 것을 알려야 할 사용자 ID를 찾는 함수.
        profile_updated_notifier: 위 사용자들에게 변경 이벤트를 보내는 함수.
    """
    profile_bp = Blueprint("profile", __name__)

    @profile_bp.route("/api/account/language", methods=["PATCH"])
    @api_login_required
    def update_account_language():
        """화면 언어 설정을 계정에 저장한다. 지원하지 않는 언어 코드는 거부한다."""
        language = (request.get_json() or {}).get("language", "ko")

        if language not in supported_languages:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "지원하지 않는 언어입니다.",
                    }
                ),
                400,
            )

        with connection_factory() as conn:
            conn.execute(
                "UPDATE users SET language = %s WHERE id = %s",
                (language, session["user_id"]),
            )
            conn.commit()

        session["language"] = language
        return jsonify({"success": True, "language": language})

    @profile_bp.route("/api/account/display-name", methods=["PATCH"])
    @api_login_required
    def update_display_name():
        """표시 이름을 바꾸고, 대화 상대 화면에도 바로 반영되도록 알린다. 빈 이름은 허용하지 않는다."""
        user_id = session["user_id"]
        data = request.get_json() or {}
        display_name = (data.get("display_name") or "").strip()

        if not display_name:
            return jsonify({"success": False, "error": "이름을 입력해주세요."})

        with connection_factory() as conn:
            conn.execute(
                "UPDATE users SET display_name = %s WHERE id = %s",
                (display_name, user_id),
            )
            recipient_ids = profile_update_recipient_ids(conn, user_id)
            conn.commit()

        profile_updated_notifier(recipient_ids, user_id)
        # 화면 렌더링에 쓰는 세션 값도 함께 갱신해 새로고침 전에도 이름이 맞게 한다.
        session["display_name"] = display_name
        return jsonify({"success": True, "display_name": display_name})

    @profile_bp.route("/api/account/profile", methods=["GET", "PATCH"])
    @api_login_required
    def account_profile():
        """GET은 내 프로필을 돌려주고, PATCH는 소개글과 공개 범위만 갱신한다.

        공개 범위는 public(전체)·friends(친구)·private(비공개) 중 하나다.
        """
        user_id = session["user_id"]

        if request.method == "GET":
            with connection_factory() as conn:
                user = conn.execute(
                    """
                    SELECT display_name, username, profile_image, cover_image,
                           bio, profile_visibility
                    FROM users
                    WHERE id = %s
                    """,
                    (user_id,),
                ).fetchone()
            return jsonify(dict(user))

        data = request.get_json() or {}
        bio = (data.get("bio") or "").strip()
        visibility = data.get("profile_visibility")

        # 공개 범위는 선택 항목이다. 값이 오면 허용된 세 가지 중 하나여야 한다.
        if visibility is not None and visibility not in {"public", "friends", "private"}:
            return (
                jsonify({"success": False, "error": "올바른 프로필 공개 범위를 선택해주세요."}),
                400,
            )
        # 소개글 상한 300자. DB 컬럼(VARCHAR(300))과 같은 값이다.
        if len(bio) > 300:
            return (
                jsonify({"success": False, "error": "소개글은 최대 300자까지 입력할 수 있습니다."}),
                400,
            )

        with connection_factory() as conn:
            if visibility is None:
                current = conn.execute(
                    "SELECT profile_visibility FROM users WHERE id = %s",
                    (user_id,),
                ).fetchone()
                visibility = current["profile_visibility"] if current else "friends"

            conn.execute(
                "UPDATE users SET bio = %s, profile_visibility = %s WHERE id = %s",
                (bio, visibility, user_id),
            )
            recipient_ids = profile_update_recipient_ids(conn, user_id)
            conn.commit()

        profile_updated_notifier(recipient_ids, user_id)
        return jsonify({"success": True, "bio": bio, "profile_visibility": visibility})

    return profile_bp

"""프로필·표시 이름·언어 등 계정 화면 설정 API를 제공합니다."""

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
    """DB 연결과 프로필 변경 알림 함수를 주입해 계정 라우트를 만듭니다."""
    profile_bp = Blueprint("profile", __name__)

    @profile_bp.route("/api/account/language", methods=["PATCH"])
    @api_login_required
    def update_account_language():
        """사용자 언어 설정을 계정에 저장한다."""
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
        """빈 표시 이름을 막고, 대화 상대에게 변경 사실을 알립니다."""
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
        session["display_name"] = display_name
        return jsonify({"success": True, "display_name": display_name})

    @profile_bp.route("/api/account/profile", methods=["GET", "PATCH"])
    @api_login_required
    def account_profile():
        """GET은 현재 프로필을 반환하고 PATCH는 소개·공개 범위만 갱신합니다."""
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

        if visibility is not None and visibility not in {"public", "friends", "private"}:
            return (
                jsonify({"success": False, "error": "올바른 프로필 공개 범위를 선택해주세요."}),
                400,
            )
        if len(bio) > 300:
            return (
                jsonify({"success": False, "error": "소개글은 최대 300자까지 입력할 수 있습니다."}),
                400,
            )

        with connection_factory() as conn:
            # PATCH에 공개 범위가 없으면 기존 설정을 유지합니다.
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

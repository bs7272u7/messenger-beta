"""친구 요청·친구 목록·차단 기능을 인증된 API로 노출합니다."""

from collections.abc import Callable
from typing import Any

from flask import Blueprint, jsonify, request, session

from services.friend_service import FriendService, FriendServiceError


def create_friends_blueprint(
    connection_factory: Callable[[], Any],
    api_login_required,
    notify_user: Callable[[int, str, dict], None],
    now_string: Callable[[], str],
    blocked_either_way: Callable[[Any, int, int], bool],
    accept_request: Callable[[Any, int], None],
    friend_service: FriendService,
) -> Blueprint:
    """친구 도메인 서비스와 실시간 알림 함수를 주입해 라우트를 만듭니다."""
    friends_bp = Blueprint("friends", __name__)

    @friends_bp.route("/api/friend-requests", methods=["POST"])
    @api_login_required
    def send_friend_request():
        """아이디로 친구 요청을 만들고, 상대 화면을 즉시 갱신합니다."""
        user_id = session["user_id"]
        username = ((request.get_json() or {}).get("username") or "").strip()
        try:
            outcome = friend_service.send_request(user_id, session.get("username", ""), username)
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        notify_user(outcome.notify_user_id, "friend_updated", {})
        return jsonify({"success": True, "autoAccepted": outcome.auto_accepted})

    @friends_bp.route("/api/friend-requests/<int:request_id>/respond", methods=["POST"])
    @api_login_required
    def respond_friend_request(request_id):
        """받은 요청의 수락·거절 결과를 요청자에게 알립니다."""
        user_id = session["user_id"]
        accepted = bool((request.get_json() or {}).get("accept"))
        try:
            requester_id = friend_service.respond(request_id, user_id, accepted)
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        notify_user(requester_id, "friend_updated", {})
        return jsonify({"success": True})

    @friends_bp.route("/api/blocks", methods=["GET"])
    @api_login_required
    def list_blocks():
        """현재 사용자의 차단 목록을 반환합니다."""
        return jsonify({"blocked": friend_service.list_blocks(session["user_id"])})

    @friends_bp.route("/api/friends", methods=["GET"])
    @api_login_required
    def list_friends():
        """채팅방 숨김 여부와 무관한 실제 친구 관계를 반환합니다."""
        return jsonify({"friends": friend_service.list_friends(session["user_id"])})

    @friends_bp.route("/api/friends/<int:target_id>", methods=["DELETE"])
    @api_login_required
    def remove_friend(target_id):
        """친구 관계만 해제하고 채팅 기록은 보존합니다."""
        user_id = session["user_id"]
        try:
            peer_id = friend_service.remove_friend(user_id, target_id)
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        notify_user(peer_id, "friend_updated", {})
        return jsonify({"success": True})

    @friends_bp.route("/api/friends/<int:target_id>/conversation", methods=["POST"])
    @api_login_required
    def open_friend_conversation(target_id):
        """숨긴 1:1 채팅방을 현재 사용자의 목록에 다시 표시합니다."""
        try:
            conversation_id = friend_service.open_friend_conversation(
                session["user_id"], target_id
            )
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        return jsonify({"success": True, "conversationId": conversation_id})

    @friends_bp.route("/api/blocks", methods=["POST"])
    @api_login_required
    def block_user():
        """대상 사용자를 차단하고 상대 화면에도 관계 변경을 알립니다."""
        user_id = session["user_id"]
        try:
            target_id = friend_service.block(user_id, (request.get_json() or {}).get("user_id"))
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        notify_user(target_id, "friend_updated", {})
        return jsonify({"success": True})

    @friends_bp.route("/api/blocks/<int:target_id>", methods=["DELETE"])
    @api_login_required
    def unblock_user(target_id):
        """직접 차단한 대상만 해제합니다."""
        friend_service.unblock(session["user_id"], target_id)
        notify_user(target_id, "friend_updated", {})
        return jsonify({"success": True})

    @friends_bp.route("/api/friend-requests/<int:request_id>", methods=["DELETE"])
    @api_login_required
    def cancel_friend_request(request_id):
        """보낸 보류 요청을 취소하고 상대의 요청함을 갱신합니다."""
        user_id = session["user_id"]
        try:
            addressee_id = friend_service.cancel(request_id, user_id)
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        notify_user(addressee_id, "friend_updated", {})
        return jsonify({"success": True})

    @friends_bp.route("/api/friend-requests", methods=["GET"])
    @api_login_required
    def list_friend_requests():
        """받은 요청과 보낸 요청을 역할별로 나눠 반환합니다."""
        user_id = session["user_id"]
        with connection_factory() as conn:
            incoming = conn.execute(
                """SELECT friend_requests.id, users.id AS user_id, users.username, users.display_name,
                          users.profile_image, friend_requests.created_at
                   FROM friend_requests JOIN users ON users.id = friend_requests.requester_id
                   WHERE friend_requests.addressee_id = %s AND friend_requests.status = 'pending'
                   ORDER BY friend_requests.created_at DESC""",
                (user_id,),
            ).fetchall()
            outgoing = conn.execute(
                """SELECT friend_requests.id, users.id AS user_id, users.username, users.display_name,
                          users.profile_image, friend_requests.created_at
                   FROM friend_requests JOIN users ON users.id = friend_requests.addressee_id
                   WHERE friend_requests.requester_id = %s AND friend_requests.status = 'pending'
                   ORDER BY friend_requests.created_at DESC""",
                (user_id,),
            ).fetchall()
        return jsonify(
            {
                "incoming": [dict(row) for row in incoming],
                "outgoing": [dict(row) for row in outgoing],
            }
        )

    return friends_bp

"""친구 요청과 차단 기능 API Blueprint."""

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
    friends_bp = Blueprint("friends", __name__)

    @friends_bp.route("/api/friend-requests", methods=["POST"])
    @api_login_required
    def send_friend_request():
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
        return jsonify({"blocked": friend_service.list_blocks(session["user_id"])})

    @friends_bp.route("/api/friends", methods=["GET"])
    @api_login_required
    def list_friends():
        return jsonify({"friends": friend_service.list_friends(session["user_id"])})

    @friends_bp.route("/api/friends/<int:target_id>", methods=["DELETE"])
    @api_login_required
    def remove_friend(target_id):
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
        friend_service.unblock(session["user_id"], target_id)
        notify_user(target_id, "friend_updated", {})
        return jsonify({"success": True})

    @friends_bp.route("/api/friend-requests/<int:request_id>", methods=["DELETE"])
    @api_login_required
    def cancel_friend_request(request_id):
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

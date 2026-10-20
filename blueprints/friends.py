"""친구 요청·친구 목록·차단 기능을 로그인한 사용자용 API로 제공한다."""

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
    """친구 서비스와 실시간 알림 함수를 주입받아 라우트를 만든다.

    Args:
        connection_factory: DB 연결을 만들어 주는 함수.
        api_login_required: 로그인 여부를 검사하는 데코레이터.
        notify_user: 특정 사용자에게 소켓 이벤트를 보내는 함수.
        friend_service: 친구 도메인 로직을 가진 서비스.
    """
    friends_bp = Blueprint("friends", __name__)

    @friends_bp.route("/api/friend-requests", methods=["POST"])
    @api_login_required
    def send_friend_request():
        """아이디로 친구 요청을 만들고 상대 화면을 바로 갱신하도록 알린다."""
        user_id = session["user_id"]
        username = ((request.get_json() or {}).get("username") or "").strip()
        try:
            outcome = friend_service.send_request(user_id, session.get("username", ""), username)
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        # 상대 브라우저가 친구 목록·메시지함을 다시 불러오도록 소켓으로 신호만 보낸다(내용은 담지 않는다).
        notify_user(outcome.notify_user_id, "friend_updated", {})
        return jsonify({"success": True, "autoAccepted": outcome.auto_accepted})

    @friends_bp.route("/api/friend-requests/<int:request_id>/respond", methods=["POST"])
    @api_login_required
    def respond_friend_request(request_id):
        """받은 친구 요청을 수락·거절하고 결과를 요청자에게 알린다."""
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
        """내가 차단한 사용자 목록을 돌려준다."""
        return jsonify({"blocked": friend_service.list_blocks(session["user_id"])})

    @friends_bp.route("/api/friends", methods=["GET"])
    @api_login_required
    def list_friends():
        """수락된 친구 목록을 돌려준다. 채팅방을 숨겼는지와는 무관하다."""
        return jsonify({"friends": friend_service.list_friends(session["user_id"])})

    @friends_bp.route("/api/friends/<int:target_id>", methods=["DELETE"])
    @api_login_required
    def remove_friend(target_id):
        """친구 관계만 끊는다. 채팅 기록은 그대로 남는다."""
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
        """숨겨 둔 1:1 대화방을 내 목록에 다시 보이게 한다."""
        try:
            conversation_id = friend_service.open_friend_conversation(session["user_id"], target_id)
        except FriendServiceError as error:
            return jsonify({"success": False, "error": str(error)}), error.status_code
        return jsonify({"success": True, "conversationId": conversation_id})

    @friends_bp.route("/api/blocks", methods=["POST"])
    @api_login_required
    def block_user():
        """사용자를 차단하고 상대 화면에도 관계 변경을 알린다."""
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
        """내가 차단한 사용자의 차단을 푼다."""
        friend_service.unblock(session["user_id"], target_id)
        notify_user(target_id, "friend_updated", {})
        return jsonify({"success": True})

    @friends_bp.route("/api/friend-requests/<int:request_id>", methods=["DELETE"])
    @api_login_required
    def cancel_friend_request(request_id):
        """내가 보낸 보류 요청을 취소하고 상대의 요청함을 갱신한다."""
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
        """받은 요청과 보낸 요청을 나눠서 돌려준다(보류 상태만)."""
        user_id = session["user_id"]
        # 받은 요청은 요청자(requester) 정보를, 보낸 요청은 수신자(addressee) 정보를 조인해 상대방 프로필을 함께 보여 준다.
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

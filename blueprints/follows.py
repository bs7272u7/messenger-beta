"""팔로우 요청·팔로워 목록·사용자 검색·메시지 요청을 로그인한 사용자용 API로 제공한다(모던 UI용)."""

from collections.abc import Callable

from flask import Blueprint, jsonify, request, session

from services.dm_request_service import DmRequestError, DmRequestService
from services.follow_service import FollowService, FollowServiceError


def create_follows_blueprint(
    api_login_required,
    notify_user: Callable[[int, str, dict], None],
    follow_service: FollowService,
    dm_request_service: DmRequestService,
    write_rate_limit,
    search_rate_limit,
) -> Blueprint:
    """서비스와 실시간 알림 함수를 주입받아 라우트를 만든다.

    Args:
        api_login_required: 로그인 여부를 검사하는 데코레이터.
        notify_user: 특정 사용자에게 소켓 이벤트를 보내는 함수.
        follow_service: 팔로우 도메인 로직을 가진 서비스.
        dm_request_service: 메시지 요청 도메인 로직을 가진 서비스.
        write_rate_limit: 상태를 바꾸는 요청의 횟수를 제한하는 데코레이터.
        search_rate_limit: 검색·목록 조회의 횟수를 제한하는 데코레이터.
    """
    follows_bp = Blueprint("follows", __name__)

    def error_response(error):
        return jsonify({"success": False, "error": str(error)}), error.status_code

    def positive_int(name, default):
        try:
            return int(request.args.get(name, default))
        except (TypeError, ValueError):
            return default

    @follows_bp.route("/api/users/<int:user_id>/summary", methods=["GET"])
    @api_login_required
    def profile_summary(user_id):
        """프로필 화면용 요약(수, 관계, 공개 범위에 따른 상세)을 돌려준다."""
        try:
            summary = follow_service.summary(session["user_id"], user_id)
        except FollowServiceError as error:
            return error_response(error)
        return jsonify({"success": True, **summary})

    @follows_bp.route("/api/profiles/<username>", methods=["GET"])
    @api_login_required
    @search_rate_limit
    def profile_summary_by_username(username):
        """아이디로 프로필 요약을 돌려준다(프로필 페이지 주소 /u/<아이디>)."""
        try:
            summary = follow_service.summary_by_username(session["user_id"], username)
        except FollowServiceError as error:
            return error_response(error)
        return jsonify({"success": True, **summary})

    @follows_bp.route("/api/users/<int:user_id>/follow", methods=["POST"])
    @api_login_required
    @write_rate_limit
    def follow_user(user_id):
        """팔로우 요청을 보낸다. 상대 메시지함에 수락 대기 요청이 생긴다."""
        try:
            outcome = follow_service.request_follow(session["user_id"], user_id)
        except FollowServiceError as error:
            return error_response(error)
        notify_user(outcome.notify_user_id, "follow_updated", {})
        return jsonify({"success": True})

    @follows_bp.route("/api/users/<int:user_id>/follow", methods=["DELETE"])
    @api_login_required
    @write_rate_limit
    def unfollow_user(user_id):
        """팔로우를 끊거나, 아직 수락되지 않은 요청을 취소한다."""
        outcome = follow_service.unfollow_or_cancel(session["user_id"], user_id)
        notify_user(outcome.notify_user_id, "follow_updated", {})
        return jsonify({"success": True})

    @follows_bp.route("/api/users/<int:user_id>/follower", methods=["DELETE"])
    @api_login_required
    @write_rate_limit
    def remove_follower(user_id):
        """나를 팔로우하는 사람을 끊는다."""
        outcome = follow_service.remove_follower(session["user_id"], user_id)
        notify_user(outcome.notify_user_id, "follow_updated", {})
        return jsonify({"success": True})

    @follows_bp.route("/api/follow-requests", methods=["GET"])
    @api_login_required
    def list_follow_requests():
        """받은 팔로우 요청과 보낸 팔로우 요청(수락 대기)을 돌려준다."""
        return jsonify({"success": True, **follow_service.list_requests(session["user_id"])})

    @follows_bp.route("/api/follow-requests/<int:request_id>/respond", methods=["POST"])
    @api_login_required
    @write_rate_limit
    def respond_follow_request(request_id):
        """받은 팔로우 요청을 수락(accept=true)하거나 거절한다."""
        accept = bool((request.get_json() or {}).get("accept"))
        try:
            outcome = follow_service.respond(session["user_id"], request_id, accept)
        except FollowServiceError as error:
            return error_response(error)
        notify_user(outcome.notify_user_id, "follow_updated", {})
        return jsonify({"success": True})

    @follows_bp.route("/api/users/<int:user_id>/followers", methods=["GET"])
    @api_login_required
    @search_rate_limit
    def list_followers(user_id):
        """사용자의 팔로워 목록(검색어 q, 페이지 limit·offset)."""
        return relation_list(user_id, "followers")

    @follows_bp.route("/api/users/<int:user_id>/following", methods=["GET"])
    @api_login_required
    @search_rate_limit
    def list_following(user_id):
        """사용자의 팔로잉 목록(검색어 q, 페이지 limit·offset)."""
        return relation_list(user_id, "following")

    def relation_list(user_id, kind):
        try:
            result = follow_service.list_relations(
                session["user_id"],
                user_id,
                kind,
                request.args.get("q", ""),
                positive_int("limit", 30),
                positive_int("offset", 0),
            )
        except FollowServiceError as error:
            return error_response(error)
        return jsonify({"success": True, **result})

    @follows_bp.route("/api/users/find", methods=["GET"])
    @api_login_required
    @search_rate_limit
    def find_users():
        """아이디나 이름의 일부로 사용자를 찾는다."""
        try:
            users = follow_service.find_users(session["user_id"], request.args.get("q", ""))
        except FollowServiceError as error:
            return error_response(error)
        return jsonify({"success": True, "users": users})

    @follows_bp.route("/api/users/<int:user_id>/message", methods=["POST"])
    @api_login_required
    @write_rate_limit
    def start_message(user_id):
        """상대와의 1:1 대화방을 열거나 만든다. 맞팔이 아니면 수락 대기(pending) 방이 된다."""
        try:
            outcome = dm_request_service.start_conversation(session["user_id"], user_id)
        except DmRequestError as error:
            return error_response(error)
        if outcome.created and outcome.state != "active":
            notify_user(user_id, "message_request_updated", {})
        return jsonify(
            {
                "success": True,
                "conversationId": outcome.conversation_id,
                "state": outcome.state,
            }
        )

    @follows_bp.route("/api/message-requests", methods=["GET"])
    @api_login_required
    def list_message_requests():
        """받은 메시지 요청(수락 대기)과 내가 거절한 요청 목록."""
        return jsonify({"success": True, **dm_request_service.list_requests(session["user_id"])})

    @follows_bp.route("/api/message-requests/<int:conversation_id>/respond", methods=["POST"])
    @api_login_required
    @write_rate_limit
    def respond_message_request(conversation_id):
        """받은 메시지 요청을 수락(accept=true)하거나 거절한다."""
        accept = bool((request.get_json() or {}).get("accept"))
        try:
            requester_id = dm_request_service.respond(session["user_id"], conversation_id, accept)
        except DmRequestError as error:
            return error_response(error)
        notify_user(requester_id, "message_request_updated", {})
        notify_user(session["user_id"], "conversation_updated", {"conversationId": conversation_id})
        return jsonify({"success": True})

    @follows_bp.route("/api/inbox-counts", methods=["GET"])
    @api_login_required
    def inbox_counts():
        """메시지함 배지용: 받은 팔로우 요청 수와 메시지 요청 수."""
        user_id = session["user_id"]
        return jsonify(
            {
                "success": True,
                "followRequests": follow_service.incoming_request_count(user_id),
                "messageRequests": dm_request_service.pending_count(user_id),
            }
        )

    return follows_bp

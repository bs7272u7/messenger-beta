"""대화방·메시지 API의 URL과 기존 핸들러 이름을 한곳에서 연결합니다."""

from collections.abc import Callable
from typing import Any

from flask import Blueprint

CHAT_ROUTES = (
    ("/api/conversations", ("GET",), "get_conversations"),
    ("/api/conversations", ("POST",), "create_group_conversation"),
    ("/api/conversations/<int:conversation_id>/theme", ("PATCH",), "update_conversation_theme"),
    (
        "/api/conversations/<int:conversation_id>/preferences",
        ("PATCH",),
        "update_conversation_preferences",
    ),
    ("/api/conversations/<int:conversation_id>/name", ("PATCH",), "rename_group_conversation"),
    ("/api/conversations/<int:conversation_id>/leave", ("DELETE",), "leave_conversation"),
    ("/api/conversations/<int:conversation_id>/disable", ("POST",), "disable_group_conversation"),
    ("/api/conversations/<int:conversation_id>/hide", ("POST",), "hide_conversation"),
    ("/api/conversations/<int:conversation_id>/members", ("GET",), "get_conversation_members"),
    ("/api/conversations/<int:conversation_id>/members", ("POST",), "invite_conversation_members"),
    (
        "/api/conversations/<int:conversation_id>/members/<int:member_user_id>",
        ("DELETE",),
        "remove_conversation_member",
    ),
    ("/api/link-preview", ("POST",), "link_preview"),
    ("/api/conversations/<int:conversation_id>/messages", ("GET",), "get_messages"),
    ("/api/conversations/<int:conversation_id>/messages", ("POST",), "send_message"),
    ("/api/conversations/<int:conversation_id>/messages/image", ("POST",), "send_image"),
    ("/api/conversations/<int:conversation_id>/messages/video", ("POST",), "send_video"),
    ("/api/conversations/<int:conversation_id>/messages/file", ("POST",), "send_file"),
    ("/api/conversations/<int:conversation_id>/messages/audio", ("POST",), "send_audio"),
    ("/api/messages/<int:message_id>/forward", ("POST",), "forward_message"),
    ("/api/messages/<int:message_id>/report", ("POST",), "report_message"),
    ("/api/messages/<int:message_id>", ("PATCH",), "edit_message"),
    ("/api/messages/<int:message_id>", ("DELETE",), "delete_message"),
    ("/api/messages/<int:message_id>/pin", ("POST",), "pin_message"),
    ("/api/messages/<int:message_id>/react", ("POST",), "react_message"),
    ("/api/conversations/<int:conversation_id>/photo", ("PATCH",), "update_group_photo"),
    ("/api/conversations/<int:conversation_id>/photo", ("DELETE",), "delete_group_photo"),
    ("/api/conversations/<int:conversation_id>/read", ("POST",), "read_conversation"),
)


def create_chat_blueprint(handlers: dict[str, Callable[..., Any]]) -> Blueprint:
    """기존 URL·endpoint 이름을 보존한 채 채팅 API를 Blueprint에 등록합니다.

    실제 처리 함수는 app.py에서 주입하므로, 라우팅 이동 중에도 공개 API가 바뀌지 않습니다.
    """
    chat_bp = Blueprint("chat", __name__)
    for rule, methods, endpoint in CHAT_ROUTES:
        chat_bp.add_url_rule(rule, endpoint=endpoint, view_func=handlers[endpoint], methods=methods)
    return chat_bp

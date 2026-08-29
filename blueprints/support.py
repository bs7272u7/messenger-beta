"""고객 문의 API Blueprint."""

import base64
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request, session
from markupsafe import escape


def create_support_blueprint(
    connection_factory: Callable[[], Any],
    api_login_required,
    delete_attachment: Callable[[str], None],
    save_attachment: Callable[[Any, str], tuple[str, str]],
    email_sender: Callable[[dict], None],
    sender_getter: Callable[[], str],
    support_email: str | None,
    kst,
    now_string: Callable[[], str],
    daily_limit: int,
    allowed_extensions: set[str],
    attachment_max_bytes: int,
    logger,
    support_rate_limit,
) -> Blueprint:
    support_bp = Blueprint("support", __name__)

    @support_bp.route("/api/support-inquiries", methods=["POST"])
    @api_login_required
    @support_rate_limit
    def send_support_inquiry():
        message = (request.form.get("message") or "").strip()
        if not 10 <= len(message) <= 3000:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "문의 내용은 10자 이상 3,000자 이하로 입력해주세요.",
                    }
                ),
                400,
            )

        user_id = session["user_id"]
        today_start = datetime.now(kst).strftime("%Y-%m-%d 00:00:00")
        with connection_factory() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM support_inquiries WHERE user_id = %s AND created_at >= %s",
                (user_id, today_start),
            ).fetchone()["count"]
        if count >= daily_limit:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "문의는 하루에 1개까지 등록할 수 있습니다. 내일 다시 시도해주세요.",
                    }
                ),
                429,
            )

        attachment = request.files.get("attachment")
        attachment_data = attachment_url = attachment_name = None
        if attachment and attachment.filename:
            extension = (
                attachment.filename.rsplit(".", 1)[-1].lower() if "." in attachment.filename else ""
            )
            if extension not in allowed_extensions:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "사진(png, jpg, gif, webp) 또는 동영상(mp4, webm, mov)만 첨부할 수 있습니다.",
                        }
                    ),
                    400,
                )
            content = attachment.read(attachment_max_bytes + 1)
            if len(content) > attachment_max_bytes:
                return (
                    jsonify(
                        {"success": False, "error": "첨부파일은 10MB 이하만 보낼 수 있습니다."}
                    ),
                    400,
                )
            safe_name = re.sub(r"[^\w.가-힣-]", "_", attachment.filename)
            attachment_data = {
                "filename": safe_name or f"attachment.{extension}",
                "content": base64.b64encode(content).decode("ascii"),
            }
            attachment.seek(0)
            attachment_url, attachment_name = save_attachment(attachment, "support")

        with connection_factory() as conn:
            user = conn.execute(
                "SELECT username, display_name, email FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        if not user:
            session.clear()
            return jsonify({"success": False, "error": "로그인 정보를 확인할 수 없습니다."}), 401

        if support_email:
            display_name = user["display_name"] or user["username"]
            params = {
                "from": sender_getter(),
                "to": [support_email],
                "subject": f"[클라우드 채팅 문의] {display_name}",
                "html": "<h2>새 문의사항</h2>"
                f"<p><strong>이름:</strong> {escape(display_name)}</p>"
                f"<p><strong>아이디:</strong> {escape(user['username'])}</p>"
                f"<p><strong>이메일:</strong> {escape(user['email'] or '등록된 이메일 없음')}</p>"
                f"<hr><p>{escape(message).replace(chr(10), '<br>')}</p>",
            }
            if user["email"]:
                params["reply_to"] = user["email"]
            if attachment_data:
                params["attachments"] = [attachment_data]
            try:
                email_sender(params)
            except Exception:
                logger.exception("문의사항 이메일 발송 실패")
        else:
            logger.warning("SUPPORT_EMAIL 미설정: 문의는 관리자 페이지에만 저장됩니다.")

        with connection_factory() as conn:
            conn.execute(
                "INSERT INTO support_inquiries (user_id, message, attachment_name, attachment_url, created_at) VALUES (%s, %s, %s, %s, %s)",
                (user_id, message, attachment_name, attachment_url, now_string()),
            )
            conn.commit()
        return jsonify(
            {"success": True, "message": "문의가 전송되었습니다. 확인 후 답변드리겠습니다."}
        )

    @support_bp.route("/api/support-inquiries/history", methods=["GET"])
    @api_login_required
    def get_my_support_inquiries():
        with connection_factory() as conn:
            rows = conn.execute(
                """SELECT id, message, attachment_name, attachment_url, status, admin_reply, created_at, answered_at
                   FROM support_inquiries WHERE user_id = %s ORDER BY id DESC""",
                (session["user_id"],),
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    @support_bp.route("/api/support-inquiries/<int:inquiry_id>", methods=["PATCH", "DELETE"])
    @api_login_required
    def update_or_delete_my_support_inquiry(inquiry_id):
        user_id = session["user_id"]
        with connection_factory() as conn:
            inquiry = conn.execute(
                """SELECT id, message, attachment_url, status FROM support_inquiries
                   WHERE id = %s AND user_id = %s""",
                (inquiry_id, user_id),
            ).fetchone()
            if not inquiry:
                return jsonify({"success": False, "error": "문의 내역을 찾을 수 없습니다."}), 404
            if request.method == "DELETE":
                conn.execute("DELETE FROM support_inquiries WHERE id = %s", (inquiry_id,))
                conn.commit()
                attachment_url = inquiry["attachment_url"]
            else:
                if inquiry["status"] != "pending":
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "답변 또는 처리된 문의는 수정할 수 없습니다.",
                            }
                        ),
                        400,
                    )
                message = ((request.get_json() or {}).get("message") or "").strip()
                if not 10 <= len(message) <= 3000:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "문의 내용은 10자 이상 3,000자 이하로 입력해주세요.",
                            }
                        ),
                        400,
                    )
                conn.execute(
                    "UPDATE support_inquiries SET message = %s WHERE id = %s", (message, inquiry_id)
                )
                conn.commit()
                return jsonify({"success": True, "message": message})
        if attachment_url:
            delete_attachment(attachment_url)
        return jsonify({"success": True})

    return support_bp

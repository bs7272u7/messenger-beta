"""고객 문의의 등록·이력 조회·수정·삭제와 첨부파일 후처리를 담당한다."""

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
    """파일 저장·이메일 발송처럼 환경마다 구현이 다른 부분을 주입받아 문의 Blueprint를 만든다.

    Args:
        delete_attachment: 저장된 첨부파일을 지우는 함수.
        save_attachment: 첨부파일을 저장하고 (URL, 원래 이름)을 돌려주는 함수.
        email_sender: 관리자에게 문의 메일을 보내는 함수.
        support_email: 문의를 받을 관리자 이메일. 없으면 메일은 보내지 않는다.
        daily_limit: 사용자당 하루 문의 한도.
        allowed_extensions: 첨부 허용 확장자.
        attachment_max_bytes: 첨부파일 최대 크기(바이트).
        support_rate_limit: IP 기준 요청 횟수 제한 데코레이터.
    """
    support_bp = Blueprint("support", __name__)

    @support_bp.route("/api/support-inquiries", methods=["POST"])
    @api_login_required
    @support_rate_limit
    def send_support_inquiry():
        """문의를 저장하고 관리자에게 메일로 알린다.

        처리 순서: 내용 길이 검증 → 하루 한도 확인 → 첨부 검증·저장 → 메일 발송 → DB 저장.
        """
        message = (request.form.get("message") or "").strip()
        # 문의 내용은 10~3,000자. 너무 짧은 문의와 과도하게 긴 본문을 함께 막는다.
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
        # 한국 시간 기준으로 오늘 0시 이후의 문의 수를 세어 하루 한도를 적용한다.
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
        # 첨부가 없을 수도 있으니 세 값을 먼저 비워 둔다.
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
            # 한도보다 1바이트만 더 읽어 보면 초과 여부를 알 수 있어, 큰 파일을 통째로 메모리에 올리지 않는다.
            content = attachment.read(attachment_max_bytes + 1)
            if len(content) > attachment_max_bytes:
                return (
                    jsonify(
                        {"success": False, "error": "첨부파일은 10MB 이하만 보낼 수 있습니다."}
                    ),
                    400,
                )
            # 메일 첨부 이름에 쓸 수 없는 문자는 밑줄로 바꾼다.
            safe_name = re.sub(r"[^\w.가-힣-]", "_", attachment.filename)
            attachment_data = {
                "filename": safe_name or f"attachment.{extension}",
                "content": base64.b64encode(content).decode("ascii"),
            }
            # 크기 검사를 하느라 끝까지 읽었으므로, 저장 함수가 처음부터 읽도록 되감는다.
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
                # 사용자가 입력한 값은 escape()로 처리해, 메일 본문에 HTML이 끼어들지 못하게 한다.
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
        """내 문의 이력을 최신순으로 돌려준다."""
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
        """내 문의를 수정(PATCH)하거나 삭제(DELETE)한다.

        관리자가 답변하거나 처리한 문의는 수정할 수 없다.
        """
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
        # DB 삭제를 확정(commit)한 뒤에 파일을 지운다. 순서가 반대면 DB 오류 시 파일만 사라진다.
        if attachment_url:
            delete_attachment(attachment_url)
        return jsonify({"success": True})

    return support_bp

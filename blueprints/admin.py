"""관리자 페이지와 운영 API의 URL을 app.py의 기존 핸들러에 연결한다.

핸들러는 app.py에 남아 있고, 이 모듈은 'URL ↔ 핸들러 이름' 대응표만 가진다.
"""

from collections.abc import Callable
from typing import Any

from flask import Blueprint

# (URL 규칙, 허용 HTTP 메서드, 핸들러 이름) 목록.
# 같은 URL에 메서드별로 다른 핸들러를 쓰는 경우(예: inquiries/<id> PATCH·DELETE)는 줄을 나눠 둔다.
ADMIN_ROUTES = (
    ("/admin", ("GET",), "admin_page"),
    ("/admin/verify", ("GET",), "admin_access_verify"),
    ("/api/admin/access-key", ("POST",), "verify_admin_access_key"),
    ("/api/admin/errors", ("GET",), "admin_recent_errors"),
    ("/api/admin/online-users", ("GET",), "admin_online_users"),
    ("/api/admin/reviews", ("GET",), "admin_reviews"),
    ("/api/admin/reviews/<int:review_id>", ("PATCH", "DELETE"), "admin_review_detail"),
    ("/api/admin/reviews/bulk-delete", ("POST",), "admin_bulk_delete_reviews"),
    ("/api/admin/notices", ("GET", "POST"), "admin_notices"),
    ("/api/admin/notices/<int:notice_id>", ("PATCH", "DELETE"), "admin_notice_detail"),
    ("/api/admin/inquiries", ("GET",), "admin_inquiries"),
    ("/api/admin/inquiries/<int:inquiry_id>", ("PATCH",), "admin_inquiry_detail"),
    ("/api/admin/inquiries/<int:inquiry_id>", ("DELETE",), "admin_delete_inquiry"),
    # 정수 변환 규칙(<int:...>)과 겹치지 않도록 bulk-delete 같은 고정 경로를 따로 둔다.
    ("/api/admin/inquiries/bulk-delete", ("POST",), "admin_bulk_delete_inquiries"),
    ("/api/admin/reports", ("GET",), "admin_reports"),
    ("/api/admin/users", ("GET",), "admin_all_users"),
    ("/api/admin/users/suspended", ("GET",), "admin_suspended_users"),
    ("/api/admin/reports/<int:report_id>", ("PATCH", "DELETE"), "admin_report_detail"),
    ("/api/admin/users/<int:user_id>/suspension", ("PATCH",), "admin_user_suspension"),
    ("/api/admin/users/<int:user_id>", ("DELETE",), "admin_delete_user"),
)


def create_admin_blueprint(handlers: dict[str, Callable[..., Any]]) -> Blueprint:
    """대응표(ADMIN_ROUTES)대로 URL 규칙을 등록한 관리자 Blueprint를 만든다.

    Args:
        handlers: 엔드포인트 이름을 키로 하는 핸들러 함수 모음. app.py의 모듈 전역에서 가져온다.
    """
    # 엔드포인트 이름을 핸들러 이름 그대로 쓰므로 url_for()로 부르는 기존 코드가 바뀌지 않는다.
    admin_bp = Blueprint("admin", __name__)
    for rule, methods, endpoint in ADMIN_ROUTES:
        admin_bp.add_url_rule(
            rule, endpoint=endpoint, view_func=handlers[endpoint], methods=methods
        )
    return admin_bp

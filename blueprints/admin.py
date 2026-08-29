"""관리자 페이지와 운영 API의 URL 등록 Blueprint."""

from collections.abc import Callable
from typing import Any

from flask import Blueprint

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
    ("/api/admin/inquiries/bulk-delete", ("POST",), "admin_bulk_delete_inquiries"),
    ("/api/admin/reports", ("GET",), "admin_reports"),
    ("/api/admin/users", ("GET",), "admin_all_users"),
    ("/api/admin/users/suspended", ("GET",), "admin_suspended_users"),
    ("/api/admin/reports/<int:report_id>", ("PATCH", "DELETE"), "admin_report_detail"),
    ("/api/admin/users/<int:user_id>/suspension", ("PATCH",), "admin_user_suspension"),
    ("/api/admin/users/<int:user_id>", ("DELETE",), "admin_delete_user"),
)


def create_admin_blueprint(handlers: dict[str, Callable[..., Any]]) -> Blueprint:
    admin_bp = Blueprint("admin", __name__)
    for rule, methods, endpoint in ADMIN_ROUTES:
        admin_bp.add_url_rule(
            rule, endpoint=endpoint, view_func=handlers[endpoint], methods=methods
        )
    return admin_bp

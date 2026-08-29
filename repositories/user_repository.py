"""users 테이블 조회를 담당하는 저장소 클래스."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class UserRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def find_for_login(self, identifier: str) -> dict[str, Any] | None:
        """아이디 또는 이메일로 로그인에 필요한 사용자 정보를 조회한다."""
        is_email = "@" in identifier

        query = (
            """
            SELECT id, username, password_hash, display_name, profile_image,
                   language, is_suspended, suspended_until, suspension_reason
            FROM users
            WHERE email = %s
        """
            if is_email
            else """
            SELECT id, username, password_hash, display_name, profile_image,
                   language, is_suspended, suspended_until, suspension_reason
            FROM users
            WHERE username = %s
        """
        )

        value = identifier.lower() if is_email else identifier

        with self._connection_factory() as conn:
            row = conn.execute(query, (value,)).fetchone()

        return dict(row) if row else None

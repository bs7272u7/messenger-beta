"""users 테이블 조회를 담당하는 저장소 계층."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class UserRepository:
    """인증에 필요한 users 조회를 DB 연결 방식과 분리한다.

    연결 생성 함수를 주입받으므로 테스트에서는 가짜 연결로 바꿔 끼울 수 있다.
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def find_for_login(self, identifier: str) -> dict[str, Any] | None:
        """아이디 또는 이메일로 로그인에 필요한 사용자 정보를 조회한다.

        Args:
            identifier: 사용자가 입력한 아이디 또는 이메일. '@'가 있으면 이메일로 본다.

        Returns:
            사용자 정보 dict. 일치하는 계정이 없으면 None.
        """
        # 이메일은 대소문자를 구분하지 않지만, 아이디는 기존 정책대로 입력 그대로 비교한다.
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

        # psycopg2의 행 객체가 연결을 닫은 뒤에도 남지 않도록 일반 dict로 복사해 돌려준다.
        return dict(row) if row else None

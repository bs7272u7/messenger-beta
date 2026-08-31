"""기존 ``users`` 테이블 행을 Flask-Login 사용자 객체로 변환합니다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask_login import UserMixin


@dataclass
class User(UserMixin):
    """세션 인증과 화면 표시에 필요한 사용자 데이터 묶음입니다.

    DB 행 전체를 뷰에 넘기지 않고, 로그인에 필요한 값만 명시적으로 보관합니다.
    """
    id: int
    username: str
    display_name: str | None
    email: str | None
    is_admin: bool
    profile_visibility: str
    is_suspended: bool
    suspended_until: float
    language: str
    chess_rating: int
    chess_wins: int
    chess_draws: int
    chess_losses: int
    created_at: str | None

    @property
    def name(self) -> str:
        """화면에 표시할 이름."""
        return self.display_name or self.username

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> User:
        """psycopg2 조회 결과를 안전한 기본값을 가진 사용자 객체로 바꿉니다."""
        return cls(
            id=row["id"],
            username=row["username"],
            display_name=row.get("display_name"),
            email=row.get("email"),
            is_admin=bool(row.get("is_admin")),
            profile_visibility=row.get("profile_visibility") or "friends",
            is_suspended=bool(row.get("is_suspended")),
            suspended_until=float(row.get("suspended_until") or 0),
            language=row.get("language") or "ko",
            chess_rating=int(row.get("chess_rating") or 400),
            chess_wins=int(row.get("chess_wins") or 0),
            chess_draws=int(row.get("chess_draws") or 0),
            chess_losses=int(row.get("chess_losses") or 0),
            created_at=row.get("created_at"),
        )

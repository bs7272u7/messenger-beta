"""users 테이블 행을 Flask-Login이 쓰는 사용자 객체로 바꾸는 모델."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flask_login import UserMixin


@dataclass
class User(UserMixin):
    """세션 인증과 화면 표시에 필요한 사용자 정보 묶음.

    DB 행 전체를 뷰에 넘기지 않고 로그인 후 필요한 값만 명시적으로 보관한다.
    UserMixin이 is_authenticated, get_id() 같은 Flask-Login 필수 기능을 제공한다.
    """

    id: int
    username: str
    display_name: str | None
    email: str | None
    is_admin: bool
    profile_visibility: str
    is_suspended: bool
    # 정지 해제 시각(epoch 초). 0이면 기간이 없는 영구 정지 또는 정지 아님.
    suspended_until: float
    language: str
    created_at: str | None

    @property
    def name(self) -> str:
        """화면에 보여 줄 이름. 표시 이름이 없으면 아이디를 쓴다."""
        return self.display_name or self.username

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> User:
        """DB 조회 결과(dict)를 User로 변환한다.

        컬럼이 NULL이거나 비어 있어도 안전한 기본값으로 채운다.
        """
        return cls(
            id=row["id"],
            username=row["username"],
            display_name=row.get("display_name"),
            email=row.get("email"),
            is_admin=bool(row.get("is_admin")),
            # 값이 비어 있는 기존 계정은 가장 보수적인 '친구 공개'로 본다.
            profile_visibility=row.get("profile_visibility") or "friends",
            is_suspended=bool(row.get("is_suspended")),
            suspended_until=float(row.get("suspended_until") or 0),
            language=row.get("language") or "ko",
            created_at=row.get("created_at"),
        )

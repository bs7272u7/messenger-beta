"""인증 관련 비즈니스 로직."""

from __future__ import annotations

from typing import Any

from werkzeug.security import check_password_hash

from repositories.user_repository import UserRepository


class AuthService:
    """저장소 조회와 비밀번호 검증을 묶어 인증 흐름을 단순화합니다."""

    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    def authenticate(
        self,
        identifier: str,
        password: str,
    ) -> dict[str, Any] | None:
        """자격 증명이 유효하면 로그인 가능한 사용자 정보를 반환한다."""
        user = self._user_repository.find_for_login(identifier)

        # 존재 여부와 비밀번호 오류를 같은 결과로 처리해 계정 존재 여부를 노출하지 않습니다.
        if user is None:
            return None

        if not check_password_hash(user["password_hash"], password):
            return None

        return user

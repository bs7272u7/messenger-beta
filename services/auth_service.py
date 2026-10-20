"""로그인 자격 증명 검증을 담당하는 서비스."""

from __future__ import annotations

from typing import Any

from werkzeug.security import check_password_hash

from repositories.user_repository import UserRepository


class AuthService:
    """저장소 조회와 비밀번호 검증을 묶어 로그인 흐름을 단순하게 만든다."""

    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    def authenticate(
        self,
        identifier: str,
        password: str,
    ) -> dict[str, Any] | None:
        """아이디(또는 이메일)와 비밀번호가 맞는지 확인한다.

        Returns:
            인증에 성공하면 사용자 정보 dict, 실패하면 None.
        """
        user = self._user_repository.find_for_login(identifier)

        # 계정이 없는 경우와 비밀번호가 틀린 경우를 같은 None으로 돌려, 응답만으로 계정 존재 여부를 알 수 없게 한다.
        if user is None:
            return None

        if not check_password_hash(user["password_hash"], password):
            return None

        return user

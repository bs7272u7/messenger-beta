"""계정 생성·변경·재설정에 공통 적용하는 비밀번호 정책."""

from __future__ import annotations

import re


class PasswordPolicy:
    """현재 서비스의 비밀번호 요구 사항을 한 곳에서 관리한다."""

    min_length = 7
    _pattern = re.compile(r"(?=.*[a-z])(?=.*[0-9])(?=.*[^a-zA-Z0-9]).{7,}")

    @classmethod
    def is_valid(cls, password: str) -> bool:
        """회원가입·변경·재설정에서 같은 규칙을 적용합니다."""
        return bool(cls._pattern.fullmatch(password))

    @classmethod
    def error_message(cls) -> str:
        """입력창과 API가 같은 안내 문구를 쓰도록 반환합니다."""
        return "비밀번호는 영어 소문자, 숫자, 특수문자를 모두 포함해 7자 이상이어야 합니다."

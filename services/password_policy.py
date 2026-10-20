"""회원가입·비밀번호 변경·재설정에 공통으로 적용하는 비밀번호 정책."""

from __future__ import annotations

import re


class PasswordPolicy:
    """비밀번호 요구 사항을 한 곳에서 관리한다. 규칙을 바꿀 때는 여기만 고치면 된다."""

    min_length = 7
    # 소문자·숫자·특수문자를 각각 하나 이상 포함하고 7자 이상이어야 한다(전방 탐색으로 조건을 각각 확인).
    # 길이를 바꾸면 min_length와 이 패턴의 {7,}를 같이 고쳐야 한다.
    _pattern = re.compile(r"(?=.*[a-z])(?=.*[0-9])(?=.*[^a-zA-Z0-9]).{7,}")

    @classmethod
    def is_valid(cls, password: str) -> bool:
        """비밀번호가 정책을 만족하는지 검사한다. 모든 입력 경로가 같은 규칙을 쓴다."""
        return bool(cls._pattern.fullmatch(password))

    @classmethod
    def error_message(cls) -> str:
        """화면과 API가 같은 안내 문구를 쓰도록 오류 메시지를 한 곳에서 돌려준다."""
        return "비밀번호는 영어 소문자, 숫자, 특수문자를 모두 포함해 7자 이상이어야 합니다."

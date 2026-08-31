"""회원가입 시 이메일 인증과 계정 생성을 처리하는 서비스."""

from __future__ import annotations

from dataclasses import dataclass

from werkzeug.security import generate_password_hash


class RegistrationError(Exception):
    """회원가입이 완료될 수 없는 예상 가능한 사유."""


@dataclass(frozen=True)
class RegisteredUser:
    """회원가입 직후 세션에 넣을 수 있는 최소 사용자 정보입니다."""

    id: int
    username: str
    display_name: str
    email: str
    language: str
    profile_image: str


class RegistrationService:
    """이메일 인증 확인부터 사용자 생성까지 한 트랜잭션으로 처리합니다."""

    def __init__(
        self,
        connection_factory,
        now_string_getter,
        default_profile_image: str,
        admin_email: str,
    ) -> None:
        self._connection_factory = connection_factory
        self._now_string_getter = now_string_getter
        self._default_profile_image = default_profile_image
        self._admin_email = admin_email

    def register(
        self,
        *,
        username: str,
        email: str,
        password: str,
        display_name: str,
        language: str,
        code: str,
    ) -> RegisteredUser:
        """검증된 이메일 코드로 계정을 만들고, 사용한 코드는 즉시 폐기합니다."""
        with self._connection_factory() as conn:
            verification = conn.execute(
                "SELECT * FROM email_verification_codes WHERE email = %s AND code = %s",
                (email, code),
            ).fetchone()
            if not verification:
                raise RegistrationError("인증번호가 올바르지 않습니다.")
            if verification["expires_at"] < self._now_string_getter():
                raise RegistrationError("인증번호가 만료되었습니다. 다시 요청해주세요.")
            if conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone():
                raise RegistrationError("이미 가입된 이메일입니다.")
            if conn.execute("SELECT id FROM users WHERE username = %s", (username,)).fetchone():
                raise RegistrationError("이미 사용 중인 아이디입니다.")

            # 표시 이름이 비어 있으면 아이디를 그대로 사용해 화면 값이 비지 않게 합니다.
            resolved_name = display_name or username
            created_at = self._now_string_getter()
            row = conn.execute(
                """
                INSERT INTO users (username, password_hash, display_name, profile_image, email, is_admin, language, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    username,
                    generate_password_hash(password),
                    resolved_name,
                    self._default_profile_image,
                    email,
                    bool(self._admin_email and email == self._admin_email),
                    language,
                    created_at,
                ),
            ).fetchone()
            # 인증 코드는 한 번만 쓰게 해 재사용 가입을 막습니다.
            conn.execute("DELETE FROM email_verification_codes WHERE email = %s", (email,))
            conn.commit()

        return RegisteredUser(
            id=row["id"],
            username=username,
            display_name=resolved_name,
            email=email,
            language=language,
            profile_image=self._default_profile_image,
        )

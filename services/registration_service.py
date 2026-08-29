"""회원가입 시 이메일 인증과 계정 생성을 처리하는 서비스."""

from __future__ import annotations

from dataclasses import dataclass

from werkzeug.security import generate_password_hash


class RegistrationError(Exception):
    """회원가입이 완료될 수 없는 예상 가능한 사유."""


@dataclass(frozen=True)
class RegisteredUser:
    id: int
    username: str
    display_name: str
    email: str
    language: str
    profile_image: str


class RegistrationService:
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

            resolved_name = display_name or username
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
                    self._now_string_getter(),
                ),
            ).fetchone()
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

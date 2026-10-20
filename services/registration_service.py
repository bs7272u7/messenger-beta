"""회원가입 시 이메일 인증 확인과 계정 생성을 처리하는 서비스."""

from __future__ import annotations

from dataclasses import dataclass

from werkzeug.security import generate_password_hash


class RegistrationError(Exception):
    """가입을 진행할 수 없는 예상 가능한 사유. 메시지는 사용자에게 그대로 보여 줘도 된다."""

    pass


@dataclass(frozen=True)
class RegisteredUser:
    """가입 직후 세션에 넣을 최소 사용자 정보. 비밀번호 같은 민감 정보는 담지 않는다."""

    id: int
    username: str
    display_name: str
    email: str
    language: str
    profile_image: str


class RegistrationService:
    """인증코드 확인부터 사용자 생성까지를 한 트랜잭션으로 처리한다."""

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
        """인증코드를 확인하고 계정을 만든다. 사용한 인증코드는 곧바로 폐기한다.

        Raises:
            RegistrationError: 코드가 틀렸거나 만료됐거나, 이메일·아이디가 이미 쓰이는 경우.
        """
        with self._connection_factory() as conn:
            verification = conn.execute(
                "SELECT * FROM email_verification_codes WHERE email = %s AND code = %s",
                (email, code),
            ).fetchone()
            if not verification:
                raise RegistrationError("인증번호가 올바르지 않습니다.")
            # 만료 시각이 'YYYY-MM-DD HH:MM:SS' 형식(KST) 문자열이라 문자열 비교만으로 시간 순서가 맞는다.
            if verification["expires_at"] < self._now_string_getter():
                raise RegistrationError("인증번호가 만료되었습니다. 다시 요청해주세요.")
            if conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone():
                raise RegistrationError("이미 가입된 이메일입니다.")
            if conn.execute("SELECT id FROM users WHERE username = %s", (username,)).fetchone():
                raise RegistrationError("이미 사용 중인 아이디입니다.")

            # 표시 이름을 비워 두면 아이디를 대신 써서 화면에 빈 이름이 나오지 않게 한다.
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
                    # ADMIN_EMAIL과 같은 이메일로 가입하면 관리자 권한이 자동으로 붙는다.
                    bool(self._admin_email and email == self._admin_email),
                    language,
                    created_at,
                ),
            ).fetchone()
            # 인증코드를 한 번만 쓰게 지워서, 같은 코드로 다시 가입하는 것을 막는다.
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

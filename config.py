"""환경 설정을 한곳에서 읽기 위한 기반 모듈입니다.

현재 app.py의 실행 방식은 건드리지 않습니다. 이후 앱 팩토리 전환 때
AppConfig.from_env()를 사용하도록 단계적으로 연결합니다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """환경 변수에서 읽은 애플리케이션 공통 설정값."""

    environment: str
    secret_key: str | None
    max_content_length: int
    session_cookie_secure: bool
    upload_directory: str
    support_email: str | None
    admin_email: str | None

    @classmethod
    def from_env(cls, root_path: str) -> "AppConfig":
        """기본값은 로컬 개발에 안전하도록 두고, 운영값은 환경 변수를 우선한다."""
        is_render = bool(os.environ.get("RENDER_EXTERNAL_URL"))
        return cls(
            environment=os.environ.get("FLASK_ENV", "development"),
            secret_key=os.environ.get("SECRET_KEY"),
            max_content_length=50 * 1024 * 1024,
            session_cookie_secure=(
                is_render
                or os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true"
            ),
            upload_directory=os.path.join(root_path, "static", "uploads"),
            support_email=os.environ.get("SUPPORT_EMAIL"),
            admin_email=(os.environ.get("ADMIN_EMAIL") or "").strip().lower() or None,
        )

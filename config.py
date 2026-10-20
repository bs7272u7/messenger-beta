"""애플리케이션 설정을 환경 변수에서 읽어 한 객체로 묶는다.

아직 app.py가 이 값을 전부 쓰지는 않는다. 앱 팩토리로 옮겨 갈 때
AppConfig.from_env()를 진입점으로 삼아 설정 읽기를 여기로 모을 예정이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """환경 변수에서 읽은 설정값 묶음. frozen이라 생성 뒤에는 바꿀 수 없다."""

    environment: str
    secret_key: str | None
    max_content_length: int
    session_cookie_secure: bool
    upload_directory: str
    support_email: str | None
    admin_email: str | None

    @classmethod
    def from_env(cls, root_path: str) -> AppConfig:
        """환경 변수로 설정 객체를 만든다.

        기본값은 로컬 개발에 맞춰 두고, 운영 환경에서는 환경 변수가 우선한다.

        Args:
            root_path: Flask 앱의 루트 경로. 업로드 폴더 위치를 계산할 때 쓴다.
        """
        # Render가 배포 환경에 자동으로 넣어 주는 변수라, 있으면 운영(HTTPS)으로 본다.
        is_render = bool(os.environ.get("RENDER_EXTERNAL_URL"))
        return cls(
            environment=os.environ.get("FLASK_ENV", "development"),
            secret_key=os.environ.get("SECRET_KEY"),
            # 요청 본문 상한 50MB. 동영상·파일 업로드가 이 한도에 걸린다.
            max_content_length=50 * 1024 * 1024,
            # HTTPS 환경(Render)에서는 쿠키를 보안 전용으로 강제하고, 로컬 HTTP에서는 꺼 둔다.
            session_cookie_secure=(
                is_render or os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true"
            ),
            upload_directory=os.path.join(root_path, "static", "uploads"),
            support_email=os.environ.get("SUPPORT_EMAIL"),
            # 가입 시 이메일 비교를 소문자로 하므로 여기서도 정규화하고, 빈 문자열은 None으로 바꾼다.
            admin_email=(os.environ.get("ADMIN_EMAIL") or "").strip().lower() or None,
        )

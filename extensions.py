"""Flask 공용 확장 객체를 한 번만 만들고 앱에 연결하는 모듈입니다."""

from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

bcrypt = Bcrypt()
csrf = CSRFProtect()
login_manager = LoginManager()


def init_extensions(app) -> None:
    """앱 생성 직후 공용 확장을 연결합니다.

    확장 객체는 모듈 수준에서 한 번만 만들고 여기서 앱에 붙입니다.
    그래야 테스트·운영 환경이 각각 다른 앱 객체를 써도 상태가 섞이지 않습니다.
    """
    bcrypt.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    # 로그인 페이지 엔드포인트 이름을 유지해, 기존 리다이렉트 동작을 바꾸지 않습니다.
    login_manager.login_view = "login_page"
    login_manager.login_message = "로그인이 필요한 기능입니다."

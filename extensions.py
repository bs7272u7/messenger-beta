"""Flask 확장 객체를 모듈 수준에서 한 번만 만들고 앱에 연결한다.

확장 객체를 앱과 분리해 두면 테스트와 운영이 서로 다른 앱 객체를 써도
확장 상태가 섞이지 않는다.
"""

from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

bcrypt = Bcrypt()
csrf = CSRFProtect()
login_manager = LoginManager()


def init_extensions(app) -> None:
    """앱 생성 직후 호출해 공용 확장을 앱에 연결한다.

    Args:
        app: 확장을 붙일 Flask 앱 객체.
    """
    bcrypt.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    # Flask-Login이 비로그인 요청을 보낼 엔드포인트 이름. 기존 리다이렉트 동작을 그대로 유지한다.
    login_manager.login_view = "login_page"
    login_manager.login_message = "로그인이 필요한 기능입니다."

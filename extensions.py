"""Flask 공용 확장 객체."""

from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

bcrypt = Bcrypt()
csrf = CSRFProtect()
login_manager = LoginManager()


def init_extensions(app):
    """앱 생성 직후 공용 확장을 연결한다."""
    bcrypt.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    # 기존 라우트가 아직 app.py에 있으므로 endpoint 이름은 현재 라우트를 사용한다.
    login_manager.login_view = "login_page"
    login_manager.login_message = "로그인이 필요한 기능입니다."

"""Cloud Chatting 서버의 중심 파일.

구성 순서: 설정·확장 초기화 → 보안(CSRF·헤더·요청 제한) → 링크 미리보기·업데이트 내역
→ DB 연결 풀과 서비스 객체 → 헬퍼 함수 → 소켓 이벤트 → 이미지·파일 저장 → DB 초기화
→ 페이지·API 라우트 → 이메일·계정 복구 → Blueprint 등록.

인증·친구·채팅 같은 도메인 로직은 services/ 로, URL 등록은 blueprints/ 로 옮겨 가는 중이라
아직 이 파일에 남아 있는 라우트가 많다. 기능을 추가할 때는
"입력 검증 → 권한 확인 → DB 저장 → 실시간 알림" 순서를 먼저 확인한다.
"""

import base64
import hmac
import io
import ipaddress
import json
import os
import random
import re
import secrets
import socket
import time
import traceback
import uuid
from collections import deque
from datetime import UTC, datetime, timedelta, timezone
from functools import wraps
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import urljoin, urlparse

import cloudinary
import cloudinary.uploader
import psycopg2
import psycopg2.extras
import psycopg2.pool
import requests
import resend
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user
from flask_socketio import SocketIO, join_room
from PIL import Image, UnidentifiedImageError
from werkzeug.security import check_password_hash, generate_password_hash

from blueprints.admin import ADMIN_ROUTES, create_admin_blueprint
from blueprints.auth import create_auth_blueprint
from blueprints.chat import CHAT_ROUTES, create_chat_blueprint
from blueprints.friends import create_friends_blueprint
from blueprints.profile import create_profile_blueprint
from blueprints.support import create_support_blueprint
from config import AppConfig
from extensions import init_extensions, login_manager
from models.user import User
from repositories.user_repository import UserRepository
from services.admin_service import AdminService, AdminServiceError
from services.auth_service import AuthService
from services.chat_service import ChatService, ChatServiceError
from services.friend_service import FriendService
from services.message_service import MessageService, MessageServiceError
from services.password_policy import PasswordPolicy
from services.registration_service import RegistrationService

try:
    from pywebpush import WebPushException, webpush
except ImportError:
    # pywebpush가 설치되지 않은 환경에서도 서버는 떠야 하므로, 푸시 기능만 꺼 둔다.
    webpush = None
    WebPushException = Exception

try:
    import sentry_sdk
except ImportError:
    # sentry-sdk가 없으면 오류 추적 없이 동작한다.
    sentry_sdk = None

# 로컬 개발에서는 .env 파일의 값을 환경 변수로 읽어 온다. 운영(Render)에서는 대시보드의 환경 변수를 쓴다.
load_dotenv()
# 이메일 발송 서비스(Resend) API 키. 없으면 인증 메일을 보낼 수 없다.
resend.api_key = os.environ.get("RESEND_API_KEY")

# Flask 앱 객체. gunicorn이 app:app 으로 이 변수를 직접 가져다 실행한다(Procfile).
app = Flask(__name__)
# 환경 변수에서 읽은 설정값(업로드 폴더, 쿠키 보안 등)을 한 번에 가져온다.
app_config = AppConfig.from_env(app.root_path)

# SENTRY_DSN이 설정된 경우에만 오류 추적을 켠다.
# 초기화가 실패해도(DSN 형식 오류 등) 서버 전체가 못 뜨는 일이 없도록 try로 감싼다.
if sentry_sdk and os.environ.get("SENTRY_DSN"):
    try:
        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"].strip().strip("\"'"), send_default_pii=True)
    except Exception as e:
        app.logger.warning("Sentry 초기화 실패, 에러 추적 없이 계속 진행합니다: %s", e)

app.config["MAX_CONTENT_LENGTH"] = app_config.max_content_length

# 운영 환경에서 SECRET_KEY 없이 뜨면 세션 서명이 예측 가능해지므로 시작 자체를 막는다.
if not os.environ.get("SECRET_KEY") and os.environ.get("RENDER_EXTERNAL_URL"):
    raise RuntimeError("운영 환경에서는 SECRET_KEY를 반드시 설정해야 합니다.")

# 로컬 개발용 기본 키. 운영에서는 위 검사 때문에 반드시 환경 변수로 바뀐다.
app.secret_key = app_config.secret_key or "dev-secret-key-change-this-in-production"

app.config.update(
    # 자바스크립트가 세션 쿠키를 읽지 못하게 한다(XSS로 인한 세션 탈취 방지).
    SESSION_COOKIE_HTTPONLY=True,
    # 다른 사이트에서 오는 POST 요청에는 쿠키를 보내지 않는다(CSRF 방어의 보조 수단).
    SESSION_COOKIE_SAMESITE="Lax",
    # 로컬 HTTP 개발은 그대로 두고, Render의 HTTPS에서는 보안 쿠키(HTTPS 전용)를 강제한다.
    SESSION_COOKIE_SECURE=app_config.session_cookie_secure,
    # Flask-WTF의 자동 검사는 끈다. 대신 아래 protect_from_csrf가 /api/ 경로의 X-CSRF-Token 헤더를 직접 검사한다.
    WTF_CSRF_CHECK_DEFAULT=False,
)

# Flask-Login(로그인 상태), Flask-Bcrypt, CSRFProtect를 앱에 연결한다.
init_extensions(app)

# CORS 허용 도메인을 따로 열지 않아, 서비스와 같은 출처의 웹소켓만 받는다. 실제 서버는 gunicorn의 gthread 워커로 돈다(Procfile).
socketio = SocketIO(app, async_mode="threading")

# 스레드 모드에서 여러 스레드가 동시에 emit하면 메시지가 꼬일 수 있어 잠금으로 직렬화한다.
_emit_lock = Lock()


def emit_safe(*args, **kwargs):
    """소켓 이벤트를 보낸다. 여러 스레드가 동시에 emit하지 않도록 잠금으로 직렬화한다."""
    with _emit_lock:
        socketio.emit(*args, **kwargs)


# 업로드 파일이 저장될 폴더. Cloudinary를 쓰지 않을 때만 로컬 디스크를 쓴다.
UPLOAD_DIR = app_config.upload_directory
SUPPORT_EMAIL = app_config.support_email
# 이 이메일로 가입한 계정이 관리자가 된다. 값이 없으면 빈 문자열(관리자 자동 지정 없음).
ADMIN_EMAIL = app_config.admin_email or ""

# 업로드 폴더가 없으면 만든다. 이미 있어도 오류가 나지 않는다.
os.makedirs(UPLOAD_DIR, exist_ok=True)
# 프로필 사진을 올리지 않은 사용자가 쓰는 기본 이미지. 삭제·교체할 때 이 값은 지우지 않는다.
DEFAULT_PROFILE_IMAGE = "/static/default_profile.png"
# Cloudinary 환경 변수 3개가 모두 있을 때만 이미지를 클라우드에 올린다. 하나라도 없으면 로컬 저장.
CLOUDINARY_ENABLED = all(
    os.environ.get(name)
    for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")
)
# 업데이트 내역을 가져올 GitHub 저장소와 토큰. 토큰이 없으면 비로그인 호출 한도(시간당 60회)를 쓴다.
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "bs7272u7/messenger-beta")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
# 업데이트 내역을 메모리에 보관하는 시간(10분). GitHub API 호출 횟수를 줄인다.
UPDATE_HISTORY_CACHE_SECONDS = 600
_update_history_cache = {
    "recent": {"expires_at": 0, "data": None},
    "all": {"expires_at": 0, "data": None},
}
# 관리자 페이지에 한 번 더 거는 접근 키(해시 값). 키 확인에 성공하면 30분간 유효하고, 5번 틀리면 15분간 잠근다.
ADMIN_ACCESS_KEY_HASH = os.environ.get("ADMIN_ACCESS_KEY_HASH")
ADMIN_ACCESS_SESSION_SECONDS = 30 * 60
ADMIN_ACCESS_MAX_FAILURES = 5
ADMIN_ACCESS_LOCK_SECONDS = 15 * 60
# 화면이 지원하는 언어. static/js/i18n.js의 언어 목록과 같아야 한다.
SUPPORTED_LANGUAGES = {"ko", "en", "zh", "ja", "es"}
# 고객 문의 첨부파일 제한: 10MB, 사진·동영상만 허용, 사용자당 하루 1건.
SUPPORT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
SUPPORT_ATTACHMENT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "webm", "mov"}
SUPPORT_INQUIRY_MAX_PER_USER = 1
# 사용자 리뷰는 한 사람당 하나만 작성할 수 있다.
REVIEW_MAX_PER_USER = 1
# 채팅 첨부파일 제한: 20MB, 문서·압축·음성 파일 확장자만 허용.
CHAT_FILE_MAX_BYTES = 20 * 1024 * 1024
CHAT_FILE_EXTENSIONS = {
    "pdf",
    "txt",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "zip",
    "mp3",
    "wav",
    "m4a",
}
# 이미지 제한: 10MB 이하, 4천만 픽셀 이하. 해상도가 큰 이미지로 메모리를 소모시키는 공격을 막는다.
IMAGE_MAX_BYTES = 10 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
# 웹 푸시 알림에 쓰는 VAPID 키. 공개키는 브라우저에, 개인키는 서버에서 전송 서명에 쓴다.
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL")
# 현재 접속 중인 소켓 연결 목록(사용자 ID → 소켓 ID 집합). 한 사용자가 여러 탭을 열 수 있어 집합으로 관리한다.
active_socket_ids = {}
active_socket_ids_lock = Lock()
# 요청 제한용 기록((scope, IP) → 요청 시각 목록). 메모리에만 있어 재시작하면 초기화된다.
_rate_limit_buckets = {}
_rate_limit_lock = Lock()
# 관리자 페이지에서 볼 최근 서버 오류. 오래된 것부터 밀려나도록 길이를 50으로 제한한다.
_recent_errors = deque(maxlen=50)
_recent_errors_lock = Lock()

# Cloudinary 계정 정보를 라이브러리에 등록한다. secure=True로 HTTPS 주소를 받는다.
if CLOUDINARY_ENABLED:
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


def get_csrf_token():
    """현재 세션의 CSRF 토큰을 돌려준다. 없으면 예측할 수 없는 값으로 새로 만든다.

    다른 사이트가 사용자 브라우저를 이용해 이 서비스에 요청을 위조하는 것을 막는 데 쓴다.
    """
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def get_interface_language():
    """화면 언어를 정한다. 우선순위는 요청 헤더 → 세션 → 한국어(기본)다.

    로그인 전 화면(회원가입 등)도 같은 언어를 쓸 수 있도록 헤더를 먼저 본다.
    """
    language = request.headers.get("X-App-Language") or session.get("language") or "ko"
    return language if language in SUPPORTED_LANGUAGES else "ko"


@app.context_processor
def inject_security_values():
    """모든 템플릿에서 csrf_token을 쓸 수 있게 한다. 프런트가 meta 태그로 읽어 API 요청 헤더에 싣는다."""
    return {"csrf_token": get_csrf_token()}


@app.before_request
def protect_from_csrf():
    """상태를 바꾸는 API 요청(POST/PUT/PATCH/DELETE)은 CSRF 헤더가 세션 토큰과 같아야 통과시킨다.

    비교는 hmac.compare_digest로 해서 응답 시간 차이로 토큰이 추측되는 것을 막는다.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if not request.path.startswith("/api/"):
        return None
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(supplied, get_csrf_token()):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "보안 토큰이 올바르지 않습니다. 페이지를 새로고침한 뒤 다시 시도해주세요.",
                }
            ),
            403,
        )
    return None


def session_token_matches(user_id) -> bool:
    """세션의 계정 토큰이 DB에 저장된 현재 토큰과 같은지 확인한다.

    세션 쿠키에는 user_id만 들어 있어서, DB를 새로 만들어 ID가 다시 1부터 매겨지면
    예전 쿠키가 새로 가입한 다른 사람의 계정으로 인식될 수 있다. 계정마다 발급해 두는
    무작위 토큰을 함께 비교해, 그 계정으로 실제 로그인한 세션만 통과시킨다.
    세션이나 DB에 토큰이 없으면(이 기능 이전의 세션, 비밀번호 재설정 직후) 일치하지 않는 것으로 본다.
    """
    supplied = session.get("session_token")
    if not supplied:
        return False
    with get_db() as conn:
        row = conn.execute("SELECT session_token FROM users WHERE id = %s", (user_id,)).fetchone()
    stored = row["session_token"] if row else None
    return bool(stored) and hmac.compare_digest(supplied, stored)


@app.before_request
def drop_stale_sessions():
    """계정 토큰이 맞지 않는 로그인 세션은 요청을 처리하기 전에 비운다.

    세션을 비운 뒤에는 각 라우트의 로그인 검사가 평소처럼 로그인 화면(또는 401)으로 보낸다.
    정적 파일 요청은 로그인과 무관하므로 DB 조회를 건너뛴다.
    """
    if request.endpoint == "static" or "user_id" not in session:
        return None
    if not session_token_matches(session["user_id"]):
        logout_user()
        session.clear()
    return None


@app.after_request
def add_security_headers(response):
    """모든 응답에 기본 보안 헤더를 붙인다.

    이미 다른 곳에서 정한 헤더는 덮어쓰지 않는다(setdefault). HTTPS 요청에는 HSTS도 붙인다.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(self), geolocation=()"
    )
    if request.is_secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.errorhandler(404)
def handle_api_404(error):
    """API 경로의 404를 JSON으로 돌려준다. 일반 페이지는 기본 오류 응답을 그대로 쓴다."""
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "요청한 항목을 찾을 수 없습니다."}), 404
    return error


@app.errorhandler(405)
def handle_api_405(error):
    """API 경로의 405(허용되지 않는 메서드)를 JSON으로 돌려준다."""
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "허용되지 않은 요청 방식입니다."}), 405
    return error


@app.errorhandler(500)
def handle_api_500(error):
    """처리되지 않은 서버 오류를 기록하고, API 경로에는 JSON 오류를 돌려준다.

    최근 오류 50건은 메모리에 보관해 관리자 페이지에서 볼 수 있게 한다.
    """
    app.logger.exception("처리되지 않은 서버 오류")
    with _recent_errors_lock:
        _recent_errors.appendleft(
            {
                "at": now_str(),
                "path": request.path,
                "method": request.method,
                "userId": session.get("user_id"),
                "traceback": traceback.format_exc()[-4000:],
            }
        )
    if request.path.startswith("/api/"):
        return (
            jsonify(
                {"success": False, "error": "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요."}
            ),
            500,
        )
    return error


def get_client_ip():
    """요청한 사용자의 IP를 돌려준다. 프록시(Render) 뒤에서는 X-Forwarded-For의 첫 주소가 실제 접속자다."""
    # 프록시가 붙여 준 헤더는 'client, proxy1, proxy2' 형태라 맨 앞 값을 쓴다.
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",", 1)[0].strip() if forwarded else (request.remote_addr or "unknown")


def get_authenticated_user_id() -> int | None:
    """로그인한 사용자 ID를 돌려준다. 로그인하지 않았으면 None이다.

    Flask-Login 세션을 먼저 보고, 없으면 예전 방식의 세션 값(session['user_id'])을 쓴다.
    """
    if current_user.is_authenticated:
        return int(current_user.id)

    legacy_user_id = session.get("user_id")
    return int(legacy_user_id) if legacy_user_id is not None else None


def rate_limit(limit, window_seconds, scope):
    """IP 단위로 요청 횟수를 제한하는 데코레이터를 만든다.

    Args:
        limit: 윈도우 안에서 허용하는 최대 요청 수.
        window_seconds: 횟수를 세는 기간(초).
        scope: 제한을 구분하는 이름. 같은 IP여도 scope가 다르면 따로 센다.

    메모리에만 기록하므로 서버가 재시작하면 초기화되고 프로세스 간에는 공유되지 않는다.
    """
    def decorator(view):
        """실제 데코레이터. 대상 뷰 함수를 요청 제한 검사로 감싼다."""
        @wraps(view)
        def wrapped(*args, **kwargs):
            """요청이 들어올 때마다 (scope, IP)별 최근 기록을 확인한다.

            윈도우를 벗어난 기록은 버리고, 한도에 도달했으면 429를 돌려준다. 통과하면 이번 요청 시각을 기록한다.
            """
            now = time.time()
            key = (scope, get_client_ip())
            with _rate_limit_lock:
                attempts = [
                    stamp
                    for stamp in _rate_limit_buckets.get(key, [])
                    if stamp > now - window_seconds
                ]
                # 윈도우 안의 요청 수가 한도에 닿으면, 가장 오래된 요청이 빠질 때까지 남은 시간을 retry_after로 알려 준다.
                if len(attempts) >= limit:
                    retry_after = max(1, int(window_seconds - (now - attempts[0])))
                    app.logger.warning("Rate limit blocked: scope=%s ip=%s", scope, get_client_ip())
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
                                "retry_after": retry_after,
                            }
                        ),
                        429,
                    )
                attempts.append(now)
                _rate_limit_buckets[key] = attempts
            return view(*args, **kwargs)

        return wrapped

    return decorator


# 가장 긴 요청 제한 윈도우(1시간)와 맞춘 기록 보존 시간.
_RATE_LIMIT_RETENTION_SECONDS = 60 * 60


def cleanup_rate_limit_buckets():
    """오래전에 요청이 끊긴 IP 기록을 30분마다 지워 메모리가 계속 늘지 않게 한다. 백그라운드 작업으로 돈다."""
    while True:
        socketio.sleep(30 * 60)
        now = time.time()
        with _rate_limit_lock:
            stale_keys = [
                key
                for key, attempts in _rate_limit_buckets.items()
                if not attempts or attempts[-1] < now - _RATE_LIMIT_RETENTION_SECONDS
            ]
            for key in stale_keys:
                _rate_limit_buckets.pop(key, None)


def cleanup_stale_db_rows():
    """6시간마다 만료된 이메일 인증코드와 비밀번호 재설정 코드를 DB에서 지운다. 백그라운드 작업으로 돈다."""
    while True:
        socketio.sleep(6 * 60 * 60)
        # 연결 풀이 없으면(DB 접속 실패 상태) 이번 정리는 건너뛴다.
        if not db_pool:
            continue
        try:
            with get_db() as conn:
                now = now_str()

                # 만료된 인증·재설정 코드는 다시 요청하기 전까지 쓸모가 없으니 바로 지운다.
                conn.execute("DELETE FROM email_verification_codes WHERE expires_at < %s", (now,))
                conn.execute("DELETE FROM password_reset_codes WHERE expires_at < %s", (now,))

                conn.commit()
        except Exception as e:
            app.logger.warning("정기 데이터 정리 실패: %s", e)


class OpenGraphParser(HTMLParser):
    """HTML에서 링크 미리보기에 필요한 최소한의 메타데이터만 뽑는 파서.

    og:/twitter: 제목·설명·이미지와 <title>만 읽고 나머지는 무시한다.
    """

    def __init__(self):
        """메타 정보를 담을 상태를 초기화한다. <title> 안쪽인지는 _in_title 플래그로 추적한다."""
        super().__init__()
        self.metadata = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        """<meta>에서 필요한 og:/twitter: 값만 모으고, <title>이 열리면 제목 수집을 시작한다. 같은 키가 여러 번 나오면 처음 값을 쓴다."""
        attributes = dict(attrs)
        if tag == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content", "").strip()
            if (
                key
                in {
                    "og:title",
                    "og:description",
                    "og:image",
                    "twitter:title",
                    "twitter:description",
                    "twitter:image",
                }
                and content
            ):
                self.metadata.setdefault(key, content)
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        """</title>이 닫히면 제목 수집을 멈춘다."""
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        """<title> 안쪽의 텍스트를 제목으로 이어 붙인다."""
        if self._in_title:
            self.title += data


def is_public_web_url(url):
    """링크 미리보기 요청이 서버 내부망을 향하지 않는지 검사한다(SSRF 방지).

    http/https이고 사용자 정보가 없으며, 호스트가 가리키는 모든 IP가 공인 주소일 때만 True다.
    """
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False
    try:
        # 도메인이 가리키는 IP를 모두 확인한다. 하나라도 내부망(사설·루프백 등)이면 거부한다.
        addresses = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
        return all(ipaddress.ip_address(address[4][0]).is_global for address in addresses)
    except (socket.gaierror, ValueError):
        return False


def get_link_preview(url):
    """링크의 제목·설명·이미지를 가져온다. 가져올 수 없거나 안전하지 않으면 None이다.

    YouTube는 공식 oEmbed로 처리하고, 그 외에는 HTML의 Open Graph 정보를 읽는다.
    리다이렉트는 직접 따라가며 매 단계마다 공인 주소인지 다시 확인한다.
    """
    try:
        current_url = url
        initial_host = (urlparse(url).hostname or "").lower()
        if initial_host == "youtu.be" or initial_host.endswith("youtube.com"):
            oembed = requests.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
                headers={"User-Agent": "Mozilla/5.0 (compatible; Messenger-Beta-LinkPreview/1.0)"},
                timeout=5,
            )
            if oembed.ok:
                data = oembed.json()
                return {
                    "url": url,
                    "domain": "YouTube",
                    "title": data.get("title", "YouTube 동영상")[:200],
                    "description": data.get("author_name", ""),
                    "image": data.get("thumbnail_url", ""),
                }
        # 리다이렉트는 최대 4번까지만 따라간다(무한 리다이렉트 방지). 단계마다 공인 주소인지 다시 검사한다.
        for _ in range(4):
            if not is_public_web_url(current_url):
                return None
            response = requests.get(
                current_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Messenger-Beta-LinkPreview/1.0)"},
                timeout=5,
                stream=True,
                # 자동으로 따라가면 내부 주소로 우회될 수 있어, 리다이렉트는 직접 처리한다.
                allow_redirects=False,
            )
            if not 300 <= response.status_code < 400:
                break
            location = response.headers.get("Location")
            if not location:
                return None
            current_url = urljoin(current_url, location)
        else:
            return None
        if response.status_code < 200 or response.status_code >= 300:
            return None
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            return None
        # 본문은 앞쪽 512KB만 읽는다. 메타 태그는 문서 앞부분에 있고, 큰 응답으로 메모리를 쓰지 않게 하려는 것이다.
        content = response.raw.read(512 * 1024, decode_content=True).decode(
            response.encoding or "utf-8", errors="replace"
        )
        parser = OpenGraphParser()
        parser.feed(content)
        parsed = urlparse(current_url)
        title = (
            parser.metadata.get("og:title")
            or parser.metadata.get("twitter:title")
            or parser.title.strip()
            or parsed.hostname
        )
        description = (
            parser.metadata.get("og:description")
            or parser.metadata.get("twitter:description")
            or ""
        )
        image = parser.metadata.get("og:image") or parser.metadata.get("twitter:image") or ""
        # data: 등 http가 아닌 이미지 주소는 버린다.
        if image and urlparse(image).scheme not in {"http", "https"}:
            image = ""
        return {
            "url": url,
            "domain": parsed.hostname,
            "title": title[:200],
            "description": description[:300],
            "image": image,
        }
    except (requests.RequestException, OSError, ValueError):
        return None


def get_update_history(include_all=False):
    """GitHub 커밋을 사용자에게 보여 줄 업데이트 내역으로 바꿔 돌려준다.

    커밋 메시지의 첫 줄이 그대로 화면에 나온다. 기본은 최근 10개, include_all이면 전체 기록이다.
    GitHub API를 매번 호출하지 않도록 각각 10분간 메모리에 캐시한다.
    """
    cache_key = "all" if include_all else "recent"
    cache = _update_history_cache[cache_key]
    if cache["data"] and time.time() < cache["expires_at"]:
        return cache["data"]

    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        updates = []
        page = 1
        # 전체 목록을 가져올 때도 한 번에 과도하게 호출하지 않도록 최대 1,000개(100개 × 10쪽)까지만 읽는다.
        while page <= 10:
            response = requests.get(
                f"https://api.github.com/repos/{GITHUB_REPOSITORY}/commits",
                params={"per_page": 100 if include_all else 10, "page": page},
                headers=headers,
                timeout=5,
            )
            response.raise_for_status()
            commits = response.json()
            for commit in commits:
                committed_at = commit["commit"]["author"]["date"]
                date = datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
                updates.append(
                    {
                        "version": commit["sha"][:7],
                        "date": date.astimezone(timezone(timedelta(hours=9))).strftime("%Y.%m.%d"),
                        "message": commit["commit"]["message"].splitlines()[0][:160],
                    }
                )

            if not include_all or "next" not in response.links:
                break
            page += 1

        result = {"updates": updates, "latest_version": updates[0]["version"] if updates else ""}
        _update_history_cache[cache_key].update(
            {
                "expires_at": time.time() + UPDATE_HISTORY_CACHE_SECONDS,
                "data": result,
            }
        )
        return result
    except (requests.RequestException, KeyError, TypeError, ValueError):
        app.logger.warning("GitHub 업데이트 내역을 불러오지 못했습니다.")
        return None


# 접속 정보는 DATABASE_URL(Render가 주는 한 줄짜리 주소)을 우선 쓰고, 없으면 아래 DB_* 값을 쓴다(로컬 개발).
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    # Render 등이 주는 postgres:// 주소를 표준 형식 postgresql:// 로 통일한다(SQLAlchemy·Alembic은 postgres:// 를 받지 않는다).
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME", "messenger-beta")
DB_PORT = int(os.environ.get("DB_PORT", 5432))
# 원격 DB(DATABASE_URL)는 SSL을 필수로, 로컬 DB는 가능하면 쓰는 쪽(prefer)을 기본으로 한다.
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require" if DATABASE_URL else "prefer")


# 유휴 연결을 중간 장비가 끊어 버리는 일을 막으려고, 30초 유휴 후 10초 간격으로 최대 5번 TCP keepalive를 보낸다.
DB_KEEPALIVE_KWARGS = dict(
    keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5
)

try:
    if DATABASE_URL:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=25, dsn=DATABASE_URL, sslmode=DB_SSLMODE, **DB_KEEPALIVE_KWARGS
        )
    else:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=25,
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME,
            port=DB_PORT,
            sslmode=DB_SSLMODE,
            **DB_KEEPALIVE_KWARGS,
        )
except Exception as e:
    app.logger.error(f"DB Connection Pool 초기화 실패: {e}")
    # 풀을 못 만들어도 서버는 뜬다. /healthz가 503을 돌려주고, get_db()는 요청마다 단일 연결을 시도한다.
    db_pool = None


class PGConn:
    """psycopg2 연결을 sqlite3처럼 conn.execute(...).fetchone() 형태로 쓰게 해 주는 어댑터.

    with 문과 함께 쓰면 블록이 끝날 때 연결을 풀(pool)에 자동으로 반납한다.
    블록 안에서 예외가 나면 롤백하고, 연결 자체가 깨졌다면 풀에 돌려보내지 않고 버린다.
    결과 행은 RealDictCursor라서 row["컬럼명"]으로 읽는다.
    """

    def __init__(self, raw_conn, pool_obj=None):
        """Args:
            raw_conn: psycopg2 연결 객체.
            pool_obj: 연결을 빌려 온 풀. None이면 close() 때 연결을 실제로 닫는다.
        """
        self.raw_conn = raw_conn
        self.pool_obj = pool_obj
        self._cursor = raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def cursor(self):
        """execute()가 쓰는 기본 커서와 별개로, 따로 쓸 새 커서를 만든다."""
        return self.raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, query, params=()):
        """쿼리를 실행하고 자기 자신을 돌려준다. 그래서 conn.execute(...).fetchone()처럼 이어 쓸 수 있다."""
        self._cursor.execute(query, params)
        return self

    @property
    def rowcount(self):
        """마지막 쿼리가 영향을 준 행 수."""
        return self._cursor.rowcount

    def fetchone(self):
        """마지막 쿼리 결과에서 한 행을 가져온다. 없으면 None."""
        return self._cursor.fetchone()

    def fetchall(self):
        """마지막 쿼리 결과 전체를 가져온다."""
        return self._cursor.fetchall()

    def commit(self):
        """지금까지의 변경을 확정한다. 호출하지 않으면 with 블록을 나갈 때 변경이 버려진다."""
        self.raw_conn.commit()

    def close(self, discard=False):
        """연결을 풀에 반납한다(풀이 없으면 닫는다).

        Args:
            discard: True면 연결을 풀에 돌려보내지 않고 폐기한다. SSL 오류 등으로 손상된 연결을 다음 요청이 재사용하지 않게 하려는 것이다.
        """
        try:
            self._cursor.close()
        except Exception:
            pass
        # 풀에서 빌린 연결이면 닫지 않고 반납한다. discard=True인 손상된 연결은 풀에 돌려보내지 않고 폐기한다.
        # 그대로 반납하면 다음 요청이 같은 SSL 오류를 다시 겪는다.
        if self.pool_obj:
            self.pool_obj.putconn(self.raw_conn, close=discard)
        else:
            self.raw_conn.close()

    def __enter__(self):
        """with 문 진입. 자기 자신을 돌려준다."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """with 블록을 나갈 때 예외가 있었다면 롤백하고, 연결 오류(OperationalError)면 연결을 폐기한 뒤 반납한다."""
        discard = False
        if exc_type:
            try:
                self.raw_conn.rollback()
            except Exception:
                discard = True
        if isinstance(exc_val, psycopg2.OperationalError):
            discard = True
        self.close(discard=discard)


def get_db():
    """DB 연결 하나를 빌려 온다. with get_db() as conn: 형태로 쓴다.

    풀이 만들어졌으면 풀에서 가져오고, 풀 초기화에 실패한 상태라면 요청마다 단일 연결을 새로 만든다.
    자동 커밋은 꺼져 있으므로 데이터를 바꾼 뒤에는 conn.commit()을 호출해야 한다.
    """
    if db_pool:
        raw_conn = db_pool.getconn()
        raw_conn.autocommit = False
        return PGConn(raw_conn, pool_obj=db_pool)
    else:
        if DATABASE_URL:
            raw_conn = psycopg2.connect(DATABASE_URL, sslmode=DB_SSLMODE)
        else:
            raw_conn = psycopg2.connect(
                host=DB_HOST,
                user=DB_USER,
                password=DB_PASSWORD,
                dbname=DB_NAME,
                port=DB_PORT,
                sslmode=DB_SSLMODE,
            )
        raw_conn.autocommit = False
        return PGConn(raw_conn)


# 서비스 객체들. 각 서비스는 DB 연결과 필요한 보조 함수를 주입받는다.
# now_str·is_blocked_either_way 등은 아래에서 정의되므로, 호출 시점에 찾도록 lambda로 감싼다.
user_repository = UserRepository(get_db)
auth_service = AuthService(user_repository)
registration_service = RegistrationService(
    get_db, lambda: now_str(), DEFAULT_PROFILE_IMAGE, ADMIN_EMAIL
)
friend_service = FriendService(
    get_db,
    lambda: now_str(),
    lambda conn, user_a, user_b: is_blocked_either_way(conn, user_a, user_b),
    lambda conn, request_id: accept_friend_request(conn, request_id),
)
chat_service = ChatService(get_db, lambda: now_str(), DEFAULT_PROFILE_IMAGE)
message_service = MessageService(
    get_db,
    lambda: now_str(),
    lambda: current_message_timestamp_ms(),
    lambda sent_at: legacy_message_labels(sent_at),
    lambda conn, conversation_id: unhide_conversation(conn, conversation_id),
)
# AdminService는 DB를 쓰지 않는 순수 검증 로직이라 주입할 것이 없다.
admin_service = AdminService()


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Flask-Login이 세션의 사용자 ID로 현재 사용자 객체를 복원할 때 호출한다.

    숫자가 아닌 ID나 DB에 없는 사용자는 None을 돌려줘 비로그인으로 처리된다.
    """
    # 세션 값이 숫자가 아니면 조작된 값으로 보고 비로그인으로 처리한다.
    if not user_id.isdigit():
        return None

    # 여기서는 with 대신 try/finally로 close()를 보장한다. 조회만 하므로 commit은 필요 없다.
    conn = get_db()
    try:
        row = conn.execute(
            """
        SELECT id, username, display_name, email, is_admin,
                   profile_visibility, is_suspended, suspended_until,
                   language, created_at
            FROM users
            WHERE id = %s

        """,
            (int(user_id),),
        ).fetchone()

        return User.from_row(row) if row else None
    finally:
        conn.close()


# === 공통 헬퍼 ===
def get_membership(conn, conversation_id, user_id):
    """사용자가 대화방의 멤버이면 멤버십 행을, 아니면 None을 돌려준다."""
    return conn.execute(
        "SELECT * FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
        (conversation_id, user_id),
    ).fetchone()


def get_owned_message(conn, user_id, message_id):
    """사용자가 접근할 수 있는(= 같은 대화방 멤버인) 메시지를 가져온다. 없으면 None.

    이름과 달리 '작성자'가 아니라 '대화방 멤버' 기준이다. 작성자 확인은 호출한 쪽에서 따로 한다.
    """
    return conn.execute(
        """
        SELECT messages.* FROM messages
        JOIN conversation_members
          ON conversation_members.conversation_id = messages.conversation_id
        WHERE messages.id = %s AND conversation_members.user_id = %s
    """,
        (message_id, user_id),
    ).fetchone()


def now_str():
    """현재 시각을 한국 시간(KST) 'YYYY-MM-DD HH:MM:SS' 문자열로 돌려준다. 서버 시간대와 상관없이 같은 값이 나온다."""
    # KST는 UTC+9이며 서머타임이 없어 고정 오프셋으로 충분하다.
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")


# 메시지 시각 변환 등 모듈 곳곳에서 쓰는 한국 시간대.
KST = timezone(timedelta(hours=9))


def current_message_timestamp_ms():
    """메시지의 기준 시각. UTC epoch 밀리초로 저장해 어느 나라에서 봐도 같은 순간을 가리키게 한다."""
    return int(time.time() * 1000)


def legacy_message_labels(sent_at_ms):
    """밀리초 시각을 예전 time/date 컬럼용 문자열로 바꾼다. 예: ('오후 3:05', '2026-10-20').

    옛 컬럼과의 호환용이라 한국 시간으로만 만들고, 화면의 실제 표시는 브라우저가 사용자 시간대로 한다.
    """
    moment = datetime.fromtimestamp(sent_at_ms / 1000, UTC).astimezone(KST)
    hour = moment.hour % 12 or 12
    return (
        f"{'오후' if moment.hour >= 12 else '오전'} {hour}:{moment.minute:02d}",
        moment.strftime("%Y-%m-%d"),
    )


def legacy_message_timestamp_ms(date_text, time_text):
    """예전 한국 시간 문자열(date, time)을 UTC 밀리초로 바꾼다. 해석할 수 없으면 None.

    '오전/오후 H:MM' 형식과 24시간제 'HH:MM' 형식을 모두 읽고, 시간이 없으면 정오로 본다.
    """
    if not date_text:
        return None
    try:
        date_value = datetime.strptime(str(date_text).replace(".", "-")[:10], "%Y-%m-%d").date()
        time_match = re.search(r"(오전|오후)\s*(\d{1,2}):(\d{2})", str(time_text or ""))
        if time_match:
            period, hour_text, minute_text = time_match.groups()
            hour, minute = int(hour_text), int(minute_text)
            # 12시간제를 24시간제로 바꾼다. 오전 12시는 0시, 오후 12시는 12시, 오후 1~11시는 +12.
            if hour == 12:
                hour = 0
            if period == "오후":
                hour += 12
        else:
            plain_time = re.search(r"(\d{1,2}):(\d{2})", str(time_text or ""))
            hour, minute = (
                # 시간 정보가 전혀 없으면 정오로 가정한다. 날짜만 알아도 정렬이 크게 틀어지지 않게 하려는 것이다.
                (int(plain_time.group(1)), int(plain_time.group(2))) if plain_time else (12, 0)
            )
        return int(
            datetime(
                date_value.year, date_value.month, date_value.day, hour, minute, tzinfo=KST
            ).timestamp()
            * 1000
        )
    except (TypeError, ValueError):
        return None


def backfill_message_timestamps(conn):
    """sent_at이 비어 있는 옛 메시지에 타임스탬프를 채운다. init_db()에서 실행하며 이미 채워진 행은 건드리지 않는다."""
    rows = conn.execute("SELECT id, date, time FROM messages WHERE sent_at IS NULL").fetchall()
    for row in rows:
        sent_at = legacy_message_timestamp_ms(row["date"], row["time"])
        if sent_at is not None:
            conn.execute("UPDATE messages SET sent_at = %s WHERE id = %s", (sent_at, row["id"]))


def get_peer_id(conn, conversation_id, user_id):
    """1:1 대화방에서 상대방의 사용자 ID를 돌려준다. 그룹이거나 대화방이 없으면 None."""
    conv = conn.execute(
        "SELECT is_group FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    # 그룹 대화방에는 '상대방'이 하나로 정해지지 않으므로 None.
    if not conv or conv["is_group"]:
        return None
    row = conn.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = %s AND user_id != %s",
        (conversation_id, user_id),
    ).fetchone()
    return row["user_id"] if row else None


def is_blocked_either_way(conn, user_a, user_b):
    """두 사용자 중 한쪽이라도 상대를 차단했으면 True."""
    row = conn.execute(
        "SELECT 1 FROM blocks WHERE (blocker_id = %s AND blocked_id = %s) OR (blocker_id = %s AND blocked_id = %s)",
        (user_a, user_b, user_b, user_a),
    ).fetchone()
    return row is not None


@socketio.on("connect")
def handle_socket_connect():
    """웹소켓 연결 시 로그인·정지 여부를 확인하고, 연결을 사용자별 방에 등록한다.

    False를 돌려주면 연결이 거부된다. 접속 사실은 다른 사용자에게 presence_updated로 알린다.
    """
    # 로그인하지 않은 연결은 거부한다.
    if "user_id" not in session:
        return False
    user_id = session["user_id"]
    # 소켓 연결에는 before_request가 실행되지 않으므로 계정 토큰을 여기서 따로 확인한다.
    if not session_token_matches(user_id):
        return False
    # 정지된 계정은 실시간 연결도 받지 않는다.
    if is_user_suspended(user_id):
        return False
    with active_socket_ids_lock:
        active_socket_ids.setdefault(user_id, set()).add(request.sid)
    # 사용자별 개인 방. 새 메시지·친구 알림 등은 이 방으로 보낸다.
    join_room(f"user_{user_id}")
    # 접속 상태가 바뀌었음을 알린다(친구 목록의 온라인 표시 갱신용).
    emit_safe("presence_updated", {"userId": user_id, "online": True})


@socketio.on("disconnect")
def handle_socket_disconnect():
    """웹소켓 연결이 끊기면 목록에서 지운다. 그 사용자의 마지막 연결일 때만 오프라인으로 알린다."""
    user_id = session.get("user_id")
    if not user_id:
        return
    with active_socket_ids_lock:
        socket_ids = active_socket_ids.get(user_id, set())
        socket_ids.discard(request.sid)
        # 아직 열려 있는 다른 탭이 있으면 오프라인으로 바꾸지 않는다.
        if socket_ids:
            return
        active_socket_ids.pop(user_id, None)
    emit_safe("presence_updated", {"userId": user_id, "online": False})


def is_user_online(user_id):
    """사용자가 현재 접속 중인지 확인한다. 한 사용자가 여러 탭을 열어도 마지막 탭까지 닫혀야 오프라인이다."""
    with active_socket_ids_lock:
        return bool(active_socket_ids.get(user_id))


def get_conversation_member_ids(conn, conversation_id):
    """대화방 참여자의 사용자 ID 목록."""
    rows = conn.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = %s", (conversation_id,)
    ).fetchall()
    return [row["user_id"] for row in rows]


def broadcast_to_conversation(conn, conversation_id, event, payload):
    """대화방 참여자 모두에게 소켓 이벤트를 보낸다.

    참여자마다 만들어 둔 개인 방(user_<id>)으로 보내기 때문에, 대화방을 열어 두지 않은 사용자도 받는다.
    """
    for uid in get_conversation_member_ids(conn, conversation_id):
        emit_safe(event, payload, room=f"user_{uid}")


def unhide_conversation(conn, conversation_id):
    """새 메시지가 오면 모든 멤버의 '숨김' 상태를 풀어, 숨겨 둔 대화방이 다시 목록에 나타나게 한다."""
    conn.execute(
        "UPDATE conversation_members SET hidden_at = NULL WHERE conversation_id = %s",
        (conversation_id,),
    )


def notify_user(user_id, event, payload):
    """특정 사용자의 개인 방(user_<id>)으로 소켓 이벤트를 보낸다."""
    emit_safe(event, payload, room=f"user_{user_id}")


def send_push_notification(conn, user_id, title, body, url="/"):
    """브라우저가 닫혀 있어도 도착하도록 Web Push 구독자 모두에게 알림을 보낸다.

    VAPID 설정이나 pywebpush가 없으면 아무것도 하지 않는다. 구독이 만료된 기기(404/410)는 DB에서 지운다.
    """
    if not (webpush and VAPID_PRIVATE_KEY and VAPID_CLAIMS_EMAIL):
        return
    subscriptions = conn.execute(
        "SELECT endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = %s",
        (user_id,),
    ).fetchall()
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
                },
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
            )
        except WebPushException as exc:
            # 404/410은 사용자가 알림 권한을 껐거나 브라우저가 구독을 만료시켰다는 뜻이다. 다음부터 보내지 않도록 지운다.
            if getattr(exc, "response", None) and exc.response.status_code in {404, 410}:
                conn.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = %s",
                    (subscription["endpoint"],),
                )
            else:
                app.logger.warning("푸시 알림 전송 실패: %s", exc)


def notify_conversation_message(conn, conversation_id, sender_id, preview):
    """대화방의 다른 멤버들에게 새 메시지 푸시를 보낸다.

    보낸 사람과, 알림을 꺼 둔(is_muted) 멤버는 제외한다. 대화방 이름이 없으면 서비스 이름을 제목으로 쓴다.
    """
    rows = conn.execute(
        """
        SELECT cm.user_id, cm.is_muted, COALESCE(c.name, '') AS conversation_name
        FROM conversation_members cm JOIN conversations c ON c.id = cm.conversation_id
        WHERE cm.conversation_id = %s AND cm.user_id != %s
    """,
        (conversation_id, sender_id),
    ).fetchall()
    for row in rows:
        if not row["is_muted"]:
            send_push_notification(
                conn,
                row["user_id"],
                row["conversation_name"] or "Cloud Chatting",
                preview,
                f"/?conversation={conversation_id}",
            )


def validate_base64_image(data_url):
    """data URL로 받은 이미지가 안전한지 검사한다.

    확장자 위장, 과도한 용량, 압축 폭탄(작은 파일이 거대한 이미지로 풀리는 공격)을 저장 전에 걸러낸다.

    Returns:
        (원본 바이트, 확장자) 튜플. 형식이 맞지 않거나 위험하면 (None, None).
    """
    match = re.fullmatch(r"data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)", data_url or "")
    # 디코딩하기 전에 base64 문자열 길이로 먼저 거른다. base64는 원본보다 약 4/3배 커진다.
    if not match or len(match.group(2)) > (IMAGE_MAX_BYTES * 4 // 3) + 4:
        return None, None
    try:
        # validate=True: base64에 허용되지 않는 문자가 섞여 있으면 거부한다.
        raw_image = base64.b64decode(match.group(2), validate=True)
        if not raw_image or len(raw_image) > IMAGE_MAX_BYTES:
            return None, None
        # Pillow의 압축 폭탄 경고 기준(픽셀 수). 이 값의 2배를 넘으면 DecompressionBombError가 난다.
        Image.MAX_IMAGE_PIXELS = IMAGE_MAX_PIXELS
        with Image.open(io.BytesIO(raw_image)) as image:
            if image.width * image.height > IMAGE_MAX_PIXELS:
                return None, None
            # 이미지 파일이 실제로 온전한 형식인지 검사한다(확장자만 위장한 파일을 거른다). verify() 뒤에는 이 객체를 다시 쓸 수 없다.
            image.verify()
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError, OSError):
        return None, None
    return raw_image, ("jpg" if match.group(1) == "jpeg" else match.group(1))


def save_base64_image(data_url):
    """검증을 통과한 base64 이미지를 저장하고, 화면에서 쓸 주소를 돌려준다. 실패하면 None.

    Cloudinary가 설정돼 있으면 그곳에 올리고, 없으면(로컬 개발) static/uploads 폴더에 저장한다.
    """
    raw_image, ext = validate_base64_image(data_url)
    if raw_image is None:
        return None
    try:
        # Render 무료 서버의 디스크는 재배포 때 지워지므로 Cloudinary가 설정돼 있으면 거기에 올린다.
        # 설정이 없는 로컬 개발에서는 static/uploads 폴더에 저장한다.
        if CLOUDINARY_ENABLED:
            result = cloudinary.uploader.upload(
                data_url,
                folder="messenger_beta/images",
                resource_type="image",
            )
            return result["secure_url"]

        # 파일 이름은 임의 UUID로 만든다. 사용자가 보낸 이름을 쓰면 덮어쓰기·경로 조작 위험이 있다.
        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(raw_image)

        return f"/static/uploads/{filename}"
    except Exception as e:
        app.logger.error("이미지 디코딩 실패: %s", e)
        return None


def delete_image_file(image_path):
    """저장된 이미지를 지운다. Cloudinary 이미지와 로컬 업로드 파일만 대상으로 하며, 그 외 주소는 건드리지 않는다.

    DB에서 메시지나 프로필을 지운 뒤 남은 파일을 정리할 때 호출한다.
    """
    if not image_path:
        return
    if CLOUDINARY_ENABLED and "/messenger_beta/images/" in image_path:
        try:
            path = urlparse(image_path).path.split("/upload/", 1)[1]
            # Cloudinary 주소의 버전 부분(v123456/)을 빼야 삭제용 public_id가 된다.
            path = re.sub(r"^v\d+/", "", path)
            cloudinary.uploader.destroy(os.path.splitext(path)[0], resource_type="image")
        except (IndexError, ValueError, KeyError):
            app.logger.warning("Cloudinary 이미지 삭제에 실패했습니다: %s", image_path)
        return
    # 서비스가 만든 업로드 경로가 아니면(외부 주소 등) 파일을 지우지 않는다.
    if not image_path.startswith("/static/uploads/"):
        return
    filepath = os.path.join(app.root_path, image_path.lstrip("/"))
    if os.path.exists(filepath):
        os.remove(filepath)


def save_uploaded_file(upload, folder="files"):
    """채팅·문의 첨부파일을 Cloudinary 또는 로컬 폴더에 저장한다.

    Args:
        upload: 업로드된 파일 객체(werkzeug FileStorage).
        folder: 저장 위치 이름(files, support 등).

    Returns:
        (파일 주소, 안전하게 바꾼 원래 이름). 확장자가 없거나 저장에 실패하면 (None, None).
    """
    original_name = os.path.basename(upload.filename or "file")
    # 파일 이름에서 경로 구분자·특수문자를 제거한다. 한글, 영문, 숫자, 점, 하이픈만 남긴다.
    safe_name = re.sub(r"[^\w.\-가-힣]", "_", original_name)
    extension = os.path.splitext(safe_name)[1].lower()
    if not safe_name or not extension:
        return None, None

    try:
        if CLOUDINARY_ENABLED:
            result = cloudinary.uploader.upload(
                upload,
                folder=f"messenger_beta/{folder}",
                resource_type="auto",
                use_filename=True,
                unique_filename=True,
            )
            return result["secure_url"], safe_name

        # 저장 이름은 UUID로 새로 만들고 확장자만 유지한다. 원래 이름은 화면 표시용으로 따로 돌려준다.
        stored_name = f"{uuid.uuid4().hex}{extension}"
        upload.save(os.path.join(UPLOAD_DIR, stored_name))
        return f"/static/uploads/{stored_name}", safe_name
    except Exception:
        app.logger.exception("첨부 파일 저장 실패")
        return None, None


# === DB 초기화 ===
def init_db():
    """서버가 시작될 때 필요한 테이블·컬럼·인덱스가 없으면 만든다.

    모든 구문이 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS 라서 여러 번 실행해도 안전하고,
    기존 데이터는 건드리지 않는다. 컬럼을 추가할 때는 기존 DB에도 적용되도록
    CREATE TABLE 안에 넣는 데서 그치지 말고 ALTER TABLE ... ADD COLUMN IF NOT EXISTS 도 함께 둔다.

    테이블 구성:
        계정   users, admin_access_attempts, moderation_actions,
               email_verification_codes, password_reset_codes
        대화   conversations, conversation_members, messages, reports
        관계   friend_requests, blocks
        운영   notices, support_inquiries, reviews, push_subscriptions
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL
            )
        """
        )

        # users는 처음에 3개 컬럼만으로 만들었고, 이후 기능이 늘 때마다 컬럼을 덧붙여 왔다.
        # CREATE TABLE만으로는 이미 있는 DB에 반영되지 않으므로 ADD COLUMN IF NOT EXISTS를 매번 실행한다.
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)")
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
        )
        # 세션이 이 계정에서 발급된 것인지 확인하는 계정 토큰(drop_stale_sessions 참고).
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_token TEXT")
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_visibility VARCHAR(20) NOT NULL DEFAULT 'friends'"
        )
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN NOT NULL DEFAULT FALSE"
        )
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_until DOUBLE PRECISION NOT NULL DEFAULT 0"
        )
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS suspension_reason TEXT")
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(5) NOT NULL DEFAULT 'ko'"
        )
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TEXT")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_access_attempts (
                user_id INT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                failed_count INT NOT NULL DEFAULT 0,
                locked_until DOUBLE PRECISION NOT NULL DEFAULT 0
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS moderation_actions (
                id SERIAL PRIMARY KEY,
                target_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                admin_user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action VARCHAR(20) NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """
        )
        # 사용자가 경고를 확인한 시각. NULL이면 아직 읽지 않은 경고다.
        cur.execute("ALTER TABLE moderation_actions ADD COLUMN IF NOT EXISTS seen_at TEXT")

        # ADMIN_EMAIL과 일치하는 계정만 관리자 권한을 부여한다.
        # 권한은 화면이나 세션이 아니라 DB에서 다시 확인하므로, 주소를 직접 입력해도 우회할 수 없다.
        if ADMIN_EMAIL:
            cur.execute(
                "UPDATE users SET is_admin = TRUE WHERE LOWER(email) = %s",
                (ADMIN_EMAIL,),
            )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS email_verification_codes (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_codes (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """
        )

        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_image TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cover_image TEXT")
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS bio VARCHAR(300) NOT NULL DEFAULT ''"
        )
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS status_message VARCHAR(100) NOT NULL DEFAULT ''"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notices (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                is_published BOOLEAN NOT NULL DEFAULT TRUE,
                created_by INT REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS support_inquiries (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                attachment_name TEXT,
                attachment_url TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                admin_reply TEXT,
                created_at TEXT NOT NULL,
                answered_at TEXT
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                endpoint TEXT UNIQUE NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
                content VARCHAR(1000) NOT NULL,
                admin_reply VARCHAR(1000),
                created_at TEXT NOT NULL,
                replied_at TEXT
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                is_group BOOLEAN NOT NULL DEFAULT FALSE,
                name TEXT,
                owner_id INT,
                profile_image TEXT,
                chat_theme VARCHAR(20) NOT NULL DEFAULT 'default',
                is_disabled BOOLEAN NOT NULL DEFAULT FALSE,
                disabled_by INT,
                last_activity_id INT NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_members (
                conversation_id INT NOT NULL,
                user_id INT NOT NULL,
                last_read_message_id INT NOT NULL DEFAULT 0,
                hidden_at TEXT,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (conversation_id, user_id),
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                conversation_id INT NOT NULL,
                sender_id INT NOT NULL,
                text TEXT,
                image TEXT,
                video TEXT,
                time TEXT,
                date TEXT,
                reply TEXT,
                edited BOOLEAN DEFAULT FALSE,
                pinned BOOLEAN DEFAULT FALSE,
                reactions TEXT,
                audio TEXT,
                message_type VARCHAR(20) NOT NULL DEFAULT 'user',
                sent_at BIGINT,
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id SERIAL PRIMARY KEY,
                reporter_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                message_id INT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                reason VARCHAR(100) NOT NULL,
                detail TEXT,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                handled_by INT REFERENCES users(id) ON DELETE SET NULL,
                handled_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (reporter_id, message_id)
            )
        """
        )
        # 메시지 신고뿐 아니라 프로필에서 '사용자 자체'를 신고할 수 있도록 message_id를 선택 항목으로 바꾼다.
        cur.execute("ALTER TABLE reports ALTER COLUMN message_id DROP NOT NULL")
        cur.execute(
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS reported_user_id INT REFERENCES users(id) ON DELETE CASCADE"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_reporter_user ON reports(reporter_id, reported_user_id) WHERE reported_user_id IS NOT NULL"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS friend_requests (
                id SERIAL PRIMARY KEY,
                requester_id INT NOT NULL,
                addressee_id INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY (requester_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (addressee_id) REFERENCES users (id) ON DELETE CASCADE,
                UNIQUE (requester_id, addressee_id)
            )
        """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS blocks (
                id SERIAL PRIMARY KEY,
                blocker_id INT NOT NULL,
                blocked_id INT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (blocker_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (blocked_id) REFERENCES users (id) ON DELETE CASCADE,
                UNIQUE (blocker_id, blocked_id)
            )
        """
        )

        # 예전 DB에 없는 컬럼을 채워 넣는 마이그레이션 목록. 이미 있으면 아무 일도 일어나지 않는다.
        for stmt in [
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_id INT",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS profile_image TEXT",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS chat_theme VARCHAR(20) NOT NULL DEFAULT 'default'",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS is_disabled BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS disabled_by INT",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_activity_id INT NOT NULL DEFAULT 0",
            "ALTER TABLE conversation_members ADD COLUMN IF NOT EXISTS hidden_at TEXT",
            "ALTER TABLE conversation_members ADD COLUMN IF NOT EXISTS chat_theme VARCHAR(20) NOT NULL DEFAULT 'default'",
            "ALTER TABLE conversation_members ADD COLUMN IF NOT EXISTS is_muted BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE conversation_members ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS video TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS file_path TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS file_name TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS file_size BIGINT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS audio TEXT",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS message_type VARCHAR(20) NOT NULL DEFAULT 'user'",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_at BIGINT",
        ]:
            cur.execute(stmt)

        # 기존 메시지는 작성 당시 한국 시간 문자열로만 저장돼 있다. UTC 기준 원본 시각(sent_at)으로 한 번만 변환해 채운다.
        backfill_message_timestamps(conn)

        cur.execute(
            """
            UPDATE conversations
            SET last_activity_id = COALESCE(
                (SELECT MAX(id) FROM messages WHERE messages.conversation_id = conversations.id),
                0
            )
            WHERE last_activity_id = 0
        """
        )

        # 자주 조회하는 컬럼에 만드는 인덱스. 대화방 목록, 친구 요청함, 차단 확인, 관리자 목록의 속도를 위한 것이다.
        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_conv_members_user ON conversation_members(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_friend_requests_addressee ON friend_requests(addressee_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_blocks_blocker ON blocks(blocker_id)",
            "CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks(blocked_id)",
            "CREATE INDEX IF NOT EXISTS idx_notices_published ON notices(is_published, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_inquiries_status ON support_inquiries(status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_inquiries_user ON support_inquiries(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at)",
        ]:
            cur.execute(stmt)

        conn.commit()
    except Exception:
        conn.raw_conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# === 로그인·권한 검사 데코레이터 ===
def login_required_page(view):
    """페이지 라우트용 로그인 검사 데코레이터.

    로그인하지 않았으면 로그인 페이지로, 정지된 계정이면 세션을 비우고 정지 안내와 함께 로그인 페이지로 보낸다.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        """로그인과 정지 여부를 검사한 뒤 원래 페이지 함수를 실행한다."""
        user_id = get_authenticated_user_id()

        if user_id is None:
            return redirect(url_for("login_page"))

        if is_user_suspended(user_id):
            logout_user()
            session.clear()
            return redirect(url_for("login_page", suspended="1"))
        return view(*args, **kwargs)

    return wrapped


def login_required_api(view):
    """API 라우트용 로그인 검사 데코레이터.

    로그인하지 않았으면 401, 정지된 계정이면 세션을 비우고 403을 JSON으로 돌려준다.
    매 요청마다 정지 여부를 DB에서 다시 확인하므로, 관리자가 정지한 즉시 효력이 생긴다.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        """로그인과 정지 여부를 검사한 뒤 원래 API 함수를 실행한다."""
        user_id = get_authenticated_user_id()

        if user_id is None:
            return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401

        if is_user_suspended(user_id):
            logout_user()
            session.clear()
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "이용 정지 상태입니다. 고객센터로 문의해주세요.",
                    }
                ),
                403,
            )

        return view(*args, **kwargs)

    return wrapped


def is_current_user_admin():
    """현재 로그인한 계정이 관리자인지 DB에서 확인한다. 세션 값이 아니라 DB를 기준으로 하므로 권한 회수가 바로 반영된다."""
    user_id = session.get("user_id")
    if not user_id:
        return False

    with get_db() as conn:
        user = conn.execute(
            "SELECT is_admin FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
    return bool(user and user["is_admin"])


def get_suspension_state(user):
    """계정의 정지 상태를 하나의 값으로 정리한다.

    Returns:
        None(정지 아님), 'permanent'(영구 정지), 'temporary'(기간 정지 진행 중),
        'expired'(기간 정지 기간이 이미 끝남. 호출한 쪽에서 정지를 풀어 주어야 한다).
    """
    if not user or not user["is_suspended"]:
        return None
    if user["suspended_until"] and user["suspended_until"] <= time.time():
        return "expired"
    return "permanent" if not user["suspended_until"] else "temporary"


def is_user_suspended(user_id):
    """사용자가 지금 정지 상태인지 확인한다. 기간 정지가 끝났다면 그 자리에서 정지를 풀고 False를 돌려준다."""
    with get_db() as conn:
        user = conn.execute(
            "SELECT is_suspended, suspended_until FROM users WHERE id = %s", (user_id,)
        ).fetchone()
        state = get_suspension_state(user)
        if state == "expired":
            conn.execute(
                "UPDATE users SET is_suspended = FALSE, suspended_until = 0, suspension_reason = NULL WHERE id = %s",
                (user_id,),
            )
            conn.commit()
            return False
    return bool(state)


# 여기부터 Blueprint를 만들어 등록한다. 의존하는 함수들(get_db, rate_limit 등)이 모두 위에서 정의된 뒤여야 해서
# 파일 중간중간에 위치한다.
auth_bp = create_auth_blueprint(
    auth_service=auth_service,
    registration_service=registration_service,
    connection_factory=get_db,
    user_loader=load_user,
    suspension_state_getter=get_suspension_state,
    supported_languages=SUPPORTED_LANGUAGES,
    # 로그인은 IP당 15분에 10번까지. 비밀번호 대입 공격을 늦춘다.
    login_rate_limit=rate_limit(10, 15 * 60, "login"),
    client_ip_getter=get_client_ip,
    api_login_required=login_required_api,
    # 회원가입은 IP당 1시간에 5번까지.
    register_rate_limit=rate_limit(5, 60 * 60, "register"),
    register_user_loader=load_user,
)
app.register_blueprint(auth_bp)


def are_users_friends(conn, user_a, user_b):
    """두 사용자가 서로 대화할 수 있는 사이인지 확인한다. 자기 자신은 항상 True.

    friend_requests가 아니라 두 사람이 함께 속한 1:1 대화방이 있는지로 판단한다.
    (프로필 공개 범위 '친구 공개'를 판단할 때 쓴다.)
    """
    # 자기 자신과는 항상 대화할 수 있는 관계로 본다.
    if user_a == user_b:
        return True
    row = conn.execute(
        """
        SELECT 1 FROM conversations c
        JOIN conversation_members first_member ON first_member.conversation_id = c.id AND first_member.user_id = %s
        JOIN conversation_members second_member ON second_member.conversation_id = c.id AND second_member.user_id = %s
        WHERE c.is_group = FALSE LIMIT 1
    """,
        (user_a, user_b),
    ).fetchone()
    return row is not None


def accept_friend_request(conn, request_id):
    """친구 요청을 수락 처리하고, 두 사람의 1:1 대화방을 새로 만든다.

    호출하는 쪽이 commit()을 해야 변경이 확정된다.

    Returns:
        새로 만든 대화방 ID.
    """
    friend_request = conn.execute(
        "SELECT * FROM friend_requests WHERE id = %s", (request_id,)
    ).fetchone()
    # 요청을 수락 상태로 바꾸고, 두 사람이 바로 대화할 수 있도록 1:1 대화방을 함께 만든다.
    conn.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = %s", (request_id,))
    conversation = conn.execute(
        "INSERT INTO conversations (is_group, name, created_at) VALUES (FALSE, NULL, %s) RETURNING id",
        (now_str(),),
    ).fetchone()
    for member_id in (friend_request["requester_id"], friend_request["addressee_id"]):
        conn.execute(
            "INSERT INTO conversation_members (conversation_id, user_id, last_read_message_id, joined_at) VALUES (%s, %s, 0, %s)",
            (conversation["id"], member_id, now_str()),
        )
    return conversation["id"]


def can_view_profile(conn, viewer_id, target):
    """viewer가 target의 프로필을 볼 수 있는지 판단한다.

    본인은 항상 볼 수 있고, 정지된 계정은 아무도 볼 수 없다.
    그 외에는 공개 범위가 public이면 모두, friends이면 친구만, private이면 본인만 볼 수 있다.
    """
    # 정지된 계정의 프로필은 본인에게도 보여 주지 않는다.
    if not target or target["is_suspended"]:
        return False
    if viewer_id == target["id"] or target["profile_visibility"] == "public":
        return True
    return target["profile_visibility"] == "friends" and are_users_friends(
        conn, viewer_id, target["id"]
    )


def is_admin_access_verified():
    """관리자 접근 키를 확인한 뒤 유효시간(30분) 안인지 본다. 지났으면 세션 값을 지우고 False."""
    verified_until = session.get("admin_verified_until", 0)
    if verified_until and float(verified_until) > time.time():
        return True
    # 유효시간이 지난 값은 지워 둔다.
    session.pop("admin_verified_until", None)
    return False


def admin_account_required_page(view):
    """관리자 계정만 통과시키는 페이지 데코레이터(접근 키 확인 전 단계용).

    관리자가 아니면 404로 응답해 관리자 페이지의 존재 자체를 숨긴다.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        """관리자 계정인지, 정지되지 않았는지 검사한 뒤 원래 페이지 함수를 실행한다."""
        if not is_current_user_admin():
            abort(404)
        if is_user_suspended(session["user_id"]):
            session.clear()
            return redirect(url_for("login_page", suspended="1"))
        return view(*args, **kwargs)

    return wrapped


def admin_account_required_api(view):
    """관리자 계정만 통과시키는 API 데코레이터(접근 키 확인 전 단계용). 관리자가 아니면 404 JSON으로 응답한다."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        """관리자 계정인지, 정지되지 않았는지 검사한 뒤 원래 API 함수를 실행한다."""
        if not is_current_user_admin():
            return jsonify({"success": False, "error": "관리자 권한이 필요합니다."}), 404
        if is_user_suspended(session["user_id"]):
            session.clear()
            return jsonify({"success": False, "error": "이용 정지 상태입니다."}), 403
        return view(*args, **kwargs)

    return wrapped


def admin_required_page(view):
    """관리자 페이지용 데코레이터. 관리자 계정이면서 접근 키 확인이 유효해야 통과한다.

    키 확인이 안 됐으면 접근 키 입력 화면으로 보낸다.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        """관리자 계정이고 접근 키 확인이 유효한지 검사한 뒤 원래 페이지 함수를 실행한다."""
        if not is_current_user_admin():
            abort(404)
        if not is_admin_access_verified():
            return redirect(url_for("admin.admin_access_verify"))
        return view(*args, **kwargs)

    return wrapped


def admin_required_api(view):
    """관리자 API용 데코레이터. 관리자 계정이면서 접근 키 확인이 유효해야 통과하고, 키 확인이 만료됐으면 403을 돌려준다."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        """관리자 계정이고 접근 키 확인이 유효한지 검사한 뒤 원래 API 함수를 실행한다."""
        if not is_current_user_admin():
            return jsonify({"success": False, "error": "관리자 권한이 필요합니다."}), 404
        if not is_admin_access_verified():
            return jsonify({"success": False, "error": "관리자 접근 키를 다시 확인해주세요."}), 403
        return view(*args, **kwargs)

    return wrapped


# === 페이지 라우트 ===
@app.get("/healthz")
def health_check():
    """서버와 DB가 살아 있는지 알려 주는 공개 점검 주소(/healthz).

    DB에 닿으면 200, 닿지 않으면 503을 돌려준다. 배포 플랫폼이 주기적으로 호출한다.
    """
    try:
        with get_db() as conn:
            # 가장 가벼운 쿼리로 DB 연결이 살아 있는지만 확인한다.
            conn.execute("SELECT 1")
            conn.fetchone()
    except Exception as error:
        app.logger.warning("헬스 체크 DB 연결 실패: %s", error)
        # 503을 돌려주면 배포 플랫폼이 이 인스턴스를 비정상으로 판단한다.
        return jsonify({"status": "degraded", "database": "unavailable"}), 503
    return jsonify({"status": "ok", "database": "available"})


@app.route("/")
def landing_page():
    """소개 페이지(/). 이미 로그인한 사용자는 바로 채팅 화면으로 보낸다."""
    if session.get("user_id"):
        return redirect(url_for("home"))
    return render_template("landing.html")


@app.route("/chat")
@login_required_page
def home():
    """채팅 화면(/chat). 로그인한 사용자 정보를 템플릿에 넘긴다.

    DB에서 계정이 사라졌다면(예: DB 초기화) 세션을 비우고 로그인 화면으로 보낸다.
    """
    user_id = session["user_id"]
    with get_db() as conn:
        user = conn.execute(
            "SELECT username, display_name, profile_image, email, language FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()

    if not user:
        session.clear()
        return redirect(url_for("login_page"))

    display_name = user["display_name"] or user["username"]
    profile_image = user["profile_image"]

    session["display_name"] = display_name
    session["profile_image"] = profile_image
    # 저장된 언어가 지원 목록에 없으면 한국어로 되돌린다.
    session["language"] = user["language"] if user["language"] in SUPPORTED_LANGUAGES else "ko"

    return render_template(
        "index.html",
        user_id=user_id,
        username=display_name,
        profile_image=profile_image,
        user_email=user["email"],
        user_language=session["language"],
    )


def conversation_is_disabled(conn, conversation_id):
    """그룹 채팅이 방장에 의해 종료됐는지 확인한다. 종료된 방에서는 메시지를 보낼 수 없다."""
    row = conn.execute(
        "SELECT is_disabled FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    return bool(row and row["is_disabled"])


def create_system_message(conn, conversation_id, text, actor_id=None):
    """'OO님이 나갔습니다', '테마를 바꿨습니다' 같은 시스템 메시지를 남긴다.

    누구의 일반 메시지도 아니므로 message_type='system'으로 저장한다. actor_id가 없으면 방장을 보낸 사람으로 둔다.

    Returns:
        새 메시지 ID. 대화방이 없으면 None.
    """
    # Render 서버는 UTC로 동작할 수 있으므로, 표시용 시각 문자열은 항상 한국 시간으로 만든다.
    sent_at = current_message_timestamp_ms()
    time_label, date_label = legacy_message_labels(sent_at)
    row = conn.execute(
        """
        INSERT INTO messages (conversation_id, sender_id, text, time, date, sent_at, edited, pinned, reactions, message_type)
        SELECT %s, COALESCE(%s, owner_id), %s, %s, %s, %s, FALSE, FALSE, %s, 'system'
        FROM conversations WHERE id = %s
        RETURNING id
    """,
        (
            conversation_id,
            actor_id,
            text,
            time_label,
            date_label,
            sent_at,
            json.dumps([]),
            conversation_id,
        ),
    ).fetchone()
    # 대화방 목록 정렬에 쓰는 last_activity_id도 이 시스템 메시지로 갱신한다.
    if row:
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (row["id"], conversation_id),
        )
    return row["id"] if row else None


def profile_update_recipient_ids(conn, user_id):
    """프로필이 바뀐 사실을 알려야 할 사용자 ID를 모은다. 나와 같은 대화방에 속한 모든 사람(나 포함)이다."""
    rows = conn.execute(
        """SELECT DISTINCT members.user_id
           FROM conversation_members mine
           JOIN conversation_members members ON members.conversation_id = mine.conversation_id
           WHERE mine.user_id = %s""",
        (user_id,),
    ).fetchall()
    return [row["user_id"] for row in rows]


def notify_profile_updated(recipient_ids, user_id):
    """프로필이 바뀌었음을 알린다. 받은 쪽 화면은 친구·대화 목록을 다시 불러온다."""
    for recipient_id in recipient_ids:
        notify_user(recipient_id, "friend_updated", {"userId": user_id})


profile_bp = create_profile_blueprint(
    connection_factory=get_db,
    supported_languages=SUPPORTED_LANGUAGES,
    api_login_required=login_required_api,
    profile_update_recipient_ids=profile_update_recipient_ids,
    profile_updated_notifier=notify_profile_updated,
)
app.register_blueprint(profile_bp)

# 문의 기능이 쓰는 의존성을 순서대로 넘긴다(인자 순서는 create_support_blueprint의 매개변수 순서와 같다).
# 문의는 IP당 1시간에 5번까지 요청할 수 있다.
support_bp = create_support_blueprint(
    get_db,
    login_required_api,
    delete_image_file,
    save_uploaded_file,
    resend.Emails.send,
    lambda: get_resend_sender(),
    SUPPORT_EMAIL,
    KST,
    now_str,
    SUPPORT_INQUIRY_MAX_PER_USER,
    SUPPORT_ATTACHMENT_EXTENSIONS,
    SUPPORT_ATTACHMENT_MAX_BYTES,
    app.logger,
    rate_limit(5, 60 * 60, "support_inquiry"),
)
app.register_blueprint(support_bp)

friends_bp = create_friends_blueprint(
    get_db,
    login_required_api,
    notify_user,
    now_str,
    is_blocked_either_way,
    accept_friend_request,
    friend_service,
)
app.register_blueprint(friends_bp)


# 관리자 페이지 라우트
# (URL은 blueprints/admin.py의 ADMIN_ROUTES에서 연결한다)
@admin_required_page
def admin_page():
    """관리자 운영 페이지의 시작 화면. 접근 키 확인까지 마친 관리자만 볼 수 있다."""
    return render_template("admin.html")


@admin_account_required_page
def admin_access_verify():
    """관리자 접근 키 입력 화면(/admin/verify). 이미 확인이 유효하면 바로 관리자 페이지로 보낸다."""
    if is_admin_access_verified():
        return redirect(url_for("admin.admin_page"))
    return render_template("admin_verify.html", access_key_configured=bool(ADMIN_ACCESS_KEY_HASH))


@admin_account_required_api
@rate_limit(8, 15 * 60, "admin_access")
def verify_admin_access_key():
    """관리자 접근 키를 확인하고, 맞으면 30분간 관리자 페이지 이용을 허용한다.

    계정 비밀번호와 별개로 한 번 더 거는 보안 장치다. 5번 틀리면 해당 관리자 계정을 15분간 잠근다.
    키는 평문이 아니라 해시(ADMIN_ACCESS_KEY_HASH)로 서버에 설정해 둔다.
    """
    # 서버에 접근 키가 설정돼 있지 않으면 확인 자체를 할 수 없다. 설정 오류이므로 503을 돌려준다.
    if not ADMIN_ACCESS_KEY_HASH:
        return (
            jsonify({"success": False, "error": "서버에 관리자 접근 키가 설정되지 않았습니다."}),
            503,
        )

    user_id = session["user_id"]
    now = time.time()
    access_key = (request.get_json() or {}).get("access_key") or ""
    with get_db() as conn:
        attempt = conn.execute(
            "SELECT failed_count, locked_until FROM admin_access_attempts WHERE user_id = %s",
            (user_id,),
        ).fetchone()
        # 이미 잠긴 계정은 키가 맞는지 확인하지 않고 남은 시간만 알려 준다.
        if attempt and attempt["locked_until"] > now:
            retry_after = max(1, int(attempt["locked_until"] - now))
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"보안을 위해 잠시 잠겼습니다. {retry_after // 60 + 1}분 후 다시 시도해주세요.",
                    }
                ),
                429,
            )

        # 성공하면 실패 기록을 지우고, 세션에 '이 시각까지 확인됨'을 기록한다.
        if check_password_hash(ADMIN_ACCESS_KEY_HASH, access_key):
            conn.execute("DELETE FROM admin_access_attempts WHERE user_id = %s", (user_id,))
            conn.commit()
            session["admin_verified_until"] = now + ADMIN_ACCESS_SESSION_SECONDS
            return jsonify({"success": True, "expires_in": ADMIN_ACCESS_SESSION_SECONDS})

        # 잠금이 이미 풀린 뒤의 실패는 횟수를 0에서 다시 센다.
        failures = (
            attempt["failed_count"] if attempt and attempt["locked_until"] <= now else 0
        ) + 1
        locked_until = (
            now + ADMIN_ACCESS_LOCK_SECONDS if failures >= ADMIN_ACCESS_MAX_FAILURES else 0
        )
        conn.execute(
            """
            INSERT INTO admin_access_attempts (user_id, failed_count, locked_until)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET failed_count = EXCLUDED.failed_count, locked_until = EXCLUDED.locked_until
        """,
            (user_id, failures, locked_until),
        )
        conn.commit()

    # 남은 시도 횟수를 알려 주되, 한도에 닿으면 잠금 안내로 바꾼다.
    remaining = ADMIN_ACCESS_MAX_FAILURES - failures
    if remaining <= 0:
        return (
            jsonify({"success": False, "error": "접근 키 입력을 5회 실패해 15분 동안 잠겼습니다."}),
            429,
        )
    return (
        jsonify(
            {"success": False, "error": f"접근 키가 올바르지 않습니다. {remaining}회 남았습니다."}
        ),
        401,
    )


@app.route("/terms")
def terms_page():
    """이용약관 페이지. 로그인 없이 볼 수 있다."""
    return render_template("legal.html", document_type="terms")


@app.route("/privacy")
def privacy_page():
    """개인정보처리방침 페이지. 로그인 없이 볼 수 있다."""
    return render_template("legal.html", document_type="privacy")


@app.route("/login")
def login_page():
    """로그인·회원가입 화면. 이미 로그인한 사용자는 채팅 화면으로 보내고, ?mode=register면 회원가입 탭으로 연다."""
    if "user_id" in session:
        return redirect(url_for("home"))
    # 랜딩 페이지의 '가입하기' 버튼이 ?mode=register로 들어오면 회원가입 탭으로 열어 준다.
    initial_mode = "register" if request.args.get("mode") == "register" else "login"
    return render_template("login.html", initial_mode=initial_mode)


@app.route("/api/push-config", methods=["GET"])
@login_required_api
def push_config():
    """브라우저가 웹 푸시를 구독할 때 필요한 공개키와 사용 가능 여부를 알려 준다."""
    return jsonify(
        {"enabled": bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY), "publicKey": VAPID_PUBLIC_KEY}
    )


@app.route("/api/push-subscriptions", methods=["POST", "DELETE"])
@login_required_api
def push_subscriptions():
    """브라우저의 푸시 구독 정보를 저장(POST)하거나 삭제(DELETE)한다.

    같은 기기(endpoint)가 다시 구독하면 소유 사용자와 키를 새 값으로 덮어쓴다.
    """
    if request.method == "DELETE":
        data = request.get_json() or {}
        endpoint = data.get("endpoint")
        if endpoint:
            with get_db() as conn:
                conn.execute(
                    "DELETE FROM push_subscriptions WHERE user_id = %s AND endpoint = %s",
                    (session["user_id"], endpoint),
                )
                conn.commit()
        return jsonify({"success": True})

    data = request.get_json() or {}
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    # 푸시 구독에는 endpoint와 암호화 키(p256dh, auth)가 모두 있어야 한다.
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return (
            jsonify({"success": False, "error": "브라우저 알림 정보를 확인하지 못했습니다."}),
            400,
        )
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (endpoint) DO UPDATE SET user_id = EXCLUDED.user_id, p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, created_at = EXCLUDED.created_at
        """,
            (session["user_id"], endpoint, keys["p256dh"], keys["auth"], now_str()),
        )
        conn.commit()
    return jsonify({"success": True})


@app.route("/api/moderation/warnings", methods=["GET"])
@login_required_api
def get_unread_moderation_warnings():
    """아직 확인하지 않은 운영 경고를 오래된 순서로 돌려준다. 경고는 다음 접속 때 한 번 확인시키는 용도다."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, reason, created_at
            FROM moderation_actions
            WHERE target_user_id = %s AND action = 'warning' AND seen_at IS NULL
            ORDER BY id ASC
        """,
            (session["user_id"],),
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/moderation/warnings/<int:warning_id>/acknowledge", methods=["POST"])
@login_required_api
def acknowledge_moderation_warning(warning_id):
    """운영 경고를 읽었다고 표시한다. 본인에게 온, 아직 읽지 않은 경고만 처리된다."""
    with get_db() as conn:
        updated = conn.execute(
            """
            UPDATE moderation_actions SET seen_at = %s
            WHERE id = %s AND target_user_id = %s AND action = 'warning' AND seen_at IS NULL
            RETURNING id
        """,
            (now_str(), warning_id, session["user_id"]),
        ).fetchone()
        conn.commit()
    if not updated:
        return jsonify({"success": False, "error": "확인할 운영 경고를 찾을 수 없습니다."}), 404
    return jsonify({"success": True})


@app.route("/api/moderation/warnings/history", methods=["GET"])
@login_required_api
def get_moderation_warning_history():
    """내가 받은 운영 경고 기록 전체를 최신순으로 돌려준다(읽은 시각 포함)."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT reason, created_at, seen_at
            FROM moderation_actions
            WHERE target_user_id = %s AND action = 'warning'
            ORDER BY id DESC
        """,
            (session["user_id"],),
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/updates", methods=["GET"])
@login_required_api
def get_updates():
    """업데이트 내역을 돌려준다(?all=1이면 전체). GitHub에서 가져오지 못하면 503."""
    update_history = get_update_history(include_all=request.args.get("all") == "1")
    if update_history is None:
        return jsonify({"success": False, "error": "업데이트 내역을 불러오지 못했습니다."}), 503
    return jsonify({"success": True, **update_history})


@app.route("/api/notices", methods=["GET"])
@login_required_api
def get_notices():
    """공개 상태인 공지사항을 최신 30개까지 돌려준다."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, content, created_at FROM notices WHERE is_published = TRUE ORDER BY id DESC LIMIT 30"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/reviews", methods=["GET", "POST"])
@login_required_api
def reviews():
    """사용자 리뷰 목록 조회(GET)와 작성(POST).

    별점은 1~5점, 후기는 5~1,000자다. 한 계정당 리뷰는 하나만 작성할 수 있다.
    """
    if request.method == "GET":
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT r.*, u.display_name, u.username, u.profile_image FROM reviews r
                JOIN users u ON u.id = r.user_id ORDER BY r.id DESC LIMIT 100
            """
            ).fetchall()
        return jsonify(
            [{**dict(row), "isMine": row["user_id"] == session["user_id"]} for row in rows]
        )
    data = request.get_json() or {}
    rating = data.get("rating")
    content = (data.get("content") or "").strip()
    if (
        not isinstance(rating, int)
        # bool도 int의 하위 타입이라 isinstance만으로는 True/False가 통과한다. 1~5 범위 검사가 그 경우도 걸러 준다.
        or rating not in range(1, 6)
        or len(content) < 5
        or len(content) > 1000
    ):
        return (
            jsonify({"success": False, "error": "별점(1~5점)과 5자 이상 후기를 입력해주세요."}),
            400,
        )
    with get_db() as conn:
        conn.execute(
            "SELECT id FROM users WHERE id = %s FOR UPDATE", (session["user_id"],)
        ).fetchone()
        # 한 계정의 동시 요청이 '개수 확인 → 삽입' 사이에 끼어들어 한도를 넘기는 것을 막으려고, 바로 위에서 사용자 행을 잠가 직렬화한다.
        review_count = conn.execute(
            "SELECT COUNT(*) AS count FROM reviews WHERE user_id = %s", (session["user_id"],)
        ).fetchone()["count"]
        if review_count >= REVIEW_MAX_PER_USER:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "리뷰는 계정당 하나만 작성할 수 있습니다. 기존 리뷰를 수정하거나 삭제한 뒤 다시 시도해주세요.",
                    }
                ),
                429,
            )
        conn.execute(
            "INSERT INTO reviews (user_id, rating, content, created_at) VALUES (%s, %s, %s, %s)",
            (session["user_id"], rating, content, now_str()),
        )
        conn.commit()
    return jsonify({"success": True})


@app.route("/api/reviews/<int:review_id>", methods=["PATCH", "DELETE"])
@login_required_api
def update_or_delete_my_review(review_id):
    """내가 쓴 리뷰만 수정(PATCH)하거나 삭제(DELETE)한다.

    수정하면 이전에 달린 관리자 답변은 지워진다(내용이 바뀌었으므로 답변이 맞지 않게 된다).
    """
    with get_db() as conn:
        review = conn.execute(
            "SELECT id FROM reviews WHERE id = %s AND user_id = %s", (review_id, session["user_id"])
        ).fetchone()
        if not review:
            return (
                jsonify({"success": False, "error": "본인 리뷰만 수정하거나 삭제할 수 있습니다."}),
                404,
            )
        if request.method == "DELETE":
            conn.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
            conn.commit()
            return jsonify({"success": True})
        data = request.get_json() or {}
        rating = data.get("rating")
        content = (data.get("content") or "").strip()
        if (
            not isinstance(rating, int)
            or rating not in range(1, 6)
            or len(content) < 5
            or len(content) > 1000
        ):
            return (
                jsonify({"success": False, "error": "별점(1~5점)과 5자 이상 후기를 입력해주세요."}),
                400,
            )
        conn.execute(
            "UPDATE reviews SET rating = %s, content = %s, admin_reply = NULL, replied_at = NULL, created_at = %s WHERE id = %s",
            (rating, content, now_str(), review_id),
        )
        conn.commit()
    return jsonify({"success": True})


# 관리자 API
# 접근 키 확인까지 끝낸 관리자만 호출할 수 있다. URL은 blueprints/admin.py에서 연결한다.
@admin_required_api
def admin_recent_errors():
    """서버 재시작 전까지 보관한 최근 500 오류(최대 50건)를 돌려준다.

    로그를 따로 열지 않고 관리자 페이지에서 바로 원인을 볼 수 있게 하려는 용도다.
    """
    with _recent_errors_lock:
        return jsonify(list(_recent_errors))


@admin_required_api
def admin_online_users():
    """지금 소켓으로 연결돼 있는(실시간 접속 중인) 사용자 수와 목록을 돌려준다."""
    with active_socket_ids_lock:
        # 잠금 안에서는 키 목록만 복사하고, DB 조회는 잠금 밖에서 한다(잠금을 오래 쥐지 않기 위해).
        user_ids = list(active_socket_ids.keys())
    # 접속 중인 사용자가 없으면 DB 조회를 생략한다(빈 목록으로 ANY()를 쓰지 않도록).
    if not user_ids:
        return jsonify({"count": 0, "users": []})
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, display_name, profile_image FROM users WHERE id = ANY(%s) ORDER BY display_name, username",
            (user_ids,),
        ).fetchall()
    return jsonify(
        {
            "count": len(rows),
            "users": [
                {
                    "id": row["id"],
                    "username": row["username"],
                    "displayName": row["display_name"] or row["username"],
                    "profileImage": row["profile_image"],
                }
                for row in rows
            ],
        }
    )


@admin_required_api
def admin_reviews():
    """전체 리뷰를 최신순으로 작성자 정보와 함께 돌려준다."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, u.display_name, u.username FROM reviews r JOIN users u ON u.id = r.user_id ORDER BY r.id DESC
        """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@admin_required_api
def admin_review_detail(review_id):
    """리뷰에 관리자 답변을 달거나(PATCH) 리뷰를 삭제한다(DELETE). 답변은 1~1,000자다."""
    with get_db() as conn:
        if request.method == "DELETE":
            conn.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
        else:
            reply = ((request.get_json() or {}).get("admin_reply") or "").strip()
            if not reply or len(reply) > 1000:
                return jsonify({"success": False, "error": "답변은 1~1,000자로 입력해주세요."}), 400
            conn.execute(
                "UPDATE reviews SET admin_reply = %s, replied_at = %s WHERE id = %s",
                (reply, now_str(), review_id),
            )
        conn.commit()
    return jsonify({"success": True})


@admin_required_api
def admin_bulk_delete_reviews():
    """선택한 리뷰만 삭제한다. 빈 목록이 전체 삭제로 해석되지 않도록 AdminService가 먼저 검증한다."""
    raw_ids = (request.get_json() or {}).get("ids")
    try:
        review_ids = admin_service.selected_ids(raw_ids, "리뷰")
    except AdminServiceError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    with get_db() as conn:
        deleted = conn.execute(
            "DELETE FROM reviews WHERE id = ANY(%s::int[])", (review_ids,)
        ).rowcount
        conn.commit()
    return jsonify({"success": True, "deleted": deleted})


@admin_required_api
def admin_notices():
    """공지사항 전체 목록을 돌려주거나(GET) 새 공지를 등록한다(POST). is_published가 False면 사용자에게는 보이지 않는다."""
    if request.method == "GET":
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, title, content, is_published, created_at, updated_at FROM notices ORDER BY id DESC"
            ).fetchall()
        return jsonify([dict(row) for row in rows])

    data = request.get_json() or {}
    try:
        title, content = admin_service.notice_content(data.get("title"), data.get("content"))
    except AdminServiceError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    timestamp = now_str()
    with get_db() as conn:
        row = conn.execute(
            """INSERT INTO notices (title, content, is_published, created_by, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                title,
                content,
                bool(data.get("is_published", True)),
                session["user_id"],
                timestamp,
                timestamp,
            ),
        ).fetchone()
        conn.commit()
    return jsonify({"success": True, "id": row["id"]})


@admin_required_api
def admin_notice_detail(notice_id):
    """공지사항을 수정(PATCH)하거나 삭제(DELETE)한다."""
    with get_db() as conn:
        # 같은 URL이 PATCH와 DELETE를 함께 받으므로 메서드로 갈라서 처리한다.
        if request.method == "DELETE":
            conn.execute("DELETE FROM notices WHERE id = %s", (notice_id,))
            conn.commit()
            return jsonify({"success": True})

        data = request.get_json() or {}
        try:
            title, content = admin_service.notice_content(data.get("title"), data.get("content"))
        except AdminServiceError as error:
            return jsonify({"success": False, "error": str(error)}), 400
        conn.execute(
            "UPDATE notices SET title = %s, content = %s, is_published = %s, updated_at = %s WHERE id = %s",
            (title, content, bool(data.get("is_published", True)), now_str(), notice_id),
        )
        conn.commit()
    return jsonify({"success": True})


@admin_required_api
def admin_inquiries():
    """고객 문의 전체를 돌려준다. 아직 처리하지 않은(pending) 문의를 맨 위에 둔다."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT i.*, u.username, u.display_name, u.email
            FROM support_inquiries i JOIN users u ON u.id = i.user_id
            ORDER BY CASE WHEN i.status = 'pending' THEN 0 ELSE 1 END, i.id DESC
        """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@admin_required_api
def admin_inquiry_detail(inquiry_id):
    """문의에 답변하고 처리 상태를 바꾼다.

    답변을 비워 두면 답변 시각도 기록하지 않는다. 허용하지 않는 상태 값은 'answered'로 처리한다.
    """
    data = request.get_json() or {}
    status = (
        data.get("status")
        if data.get("status") in {"pending", "answered", "closed"}
        else "answered"
    )
    reply = (data.get("admin_reply") or "").strip()
    with get_db() as conn:
        conn.execute(
            "UPDATE support_inquiries SET status = %s, admin_reply = %s, answered_at = %s WHERE id = %s",
            (status, reply or None, now_str() if reply else None, inquiry_id),
        )
        conn.commit()
    return jsonify({"success": True})


@admin_required_api
def admin_delete_inquiry(inquiry_id):
    """문의 한 건을 삭제한다. 첨부파일 원본은 실수로 증거가 사라지지 않도록 자동으로 지우지 않는다."""
    with get_db() as conn:
        deleted = conn.execute(
            "DELETE FROM support_inquiries WHERE id = %s", (inquiry_id,)
        ).rowcount
        conn.commit()
    if not deleted:
        return (
            jsonify({"success": False, "error": "이미 삭제되었거나 존재하지 않는 문의입니다."}),
            404,
        )
    return jsonify({"success": True, "deleted": 1})


@admin_required_api
def admin_bulk_delete_inquiries():
    """선택한 문의만 삭제한다. 빈 목록이 전체 삭제로 해석되지 않도록 AdminService가 먼저 검증한다."""
    raw_ids = (request.get_json() or {}).get("ids")
    try:
        inquiry_ids = admin_service.selected_ids(raw_ids, "문의")
    except AdminServiceError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    with get_db() as conn:
        deleted = conn.execute(
            "DELETE FROM support_inquiries WHERE id = ANY(%s::int[])", (inquiry_ids,)
        ).rowcount
        conn.commit()
    return jsonify({"success": True, "deleted": deleted})


@admin_required_api
def admin_reports():
    """신고 목록을 돌려준다. 처리하지 않은 신고를 먼저, 그 안에서는 최신순이다.

    메시지 신고와 사용자 신고를 한 목록으로 합치고, 신고 대상의 현재 정지 상태도 함께 담는다.
    """
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, reporter.username AS reporter_username,
                   COALESCE(sender.username, reported.username) AS sender_username,
                   m.text AS message_text,
                   COALESCE(m.sender_id, r.reported_user_id) AS target_user_id,
                   COALESCE(sender.is_suspended, reported.is_suspended) AS is_suspended,
                   COALESCE(sender.suspended_until, reported.suspended_until) AS suspended_until,
                   COALESCE(sender.suspension_reason, reported.suspension_reason) AS suspension_reason
            FROM reports r
            JOIN users reporter ON reporter.id = r.reporter_id
            LEFT JOIN messages m ON m.id = r.message_id
            LEFT JOIN users sender ON sender.id = m.sender_id
            LEFT JOIN users reported ON reported.id = r.reported_user_id
            ORDER BY CASE WHEN r.status = 'pending' THEN 0 ELSE 1 END, r.id DESC
        """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@admin_required_api
def admin_all_users():
    """가입한 전체 사용자를 페이지 단위로 돌려준다(아이디, 이메일, 가입일, 정지 상태 포함).

    Query:
        page: 쪽 번호(기본 1).
        page_size: 쪽당 개수(기본 50, 최대 100).
        search: 아이디·이메일·표시 이름 부분 검색.
    """
    # 잘못된 쪽 번호가 들어와도 안전한 범위로 맞춘다(쪽당 개수는 1~100).
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page_size = min(100, max(1, request.args.get("page_size", 50, type=int) or 50))
    search = (request.args.get("search") or "").strip()
    offset = (page - 1) * page_size

    with get_db() as conn:
        conn.execute(
            """UPDATE users
               SET is_suspended = FALSE, suspended_until = 0, suspension_reason = NULL
               WHERE is_suspended = TRUE AND suspended_until > 0 AND suspended_until <= %s""",
            (time.time(),),
        )
        # 검색어가 있을 때만 WHERE를 붙인다. 값은 %s 자리표시자로 넘겨 SQL 주입을 막는다(f-string에는 고정 문장만 넣는다).
        where_sql, params = "", []
        if search:
            where_sql = "WHERE username ILIKE %s OR email ILIKE %s OR display_name ILIKE %s"
            like = f"%{search}%"
            params = [like, like, like]

        total = conn.execute(f"SELECT COUNT(*) AS c FROM users {where_sql}", params).fetchone()["c"]
        rows = conn.execute(
            f"""
            SELECT id, username, email, display_name, created_at, is_admin,
                   is_suspended, suspended_until, suspension_reason
            FROM users
            {where_sql}
            ORDER BY id DESC
            LIMIT %s OFFSET %s
        """,
            params + [page_size, offset],
        ).fetchall()
        conn.commit()
    return jsonify(
        {
            "users": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@admin_required_api
def admin_suspended_users():
    """지금 이용이 제한된 계정만 모아 돌려준다. 신고 목록과 무관하게 관리자가 해제할 수 있게 하려는 것이다."""
    with get_db() as conn:
        conn.execute(
            """UPDATE users
               SET is_suspended = FALSE, suspended_until = 0, suspension_reason = NULL
               WHERE is_suspended = TRUE AND suspended_until > 0 AND suspended_until <= %s""",
            (time.time(),),
        )
        rows = conn.execute(
            """
            SELECT id, username, display_name, profile_image, suspended_until, suspension_reason
            FROM users
            WHERE is_suspended = TRUE
            ORDER BY CASE WHEN suspended_until = 0 THEN 0 ELSE 1 END, suspended_until ASC, id DESC
        """
        ).fetchall()
        conn.commit()
    return jsonify([dict(row) for row in rows])


@admin_required_api
def admin_report_detail(report_id):
    """신고의 처리 상태를 바꾸거나(PATCH) 신고 기록을 삭제한다(DELETE)."""
    if request.method == "DELETE":
        with get_db() as conn:
            deleted = conn.execute(
                "DELETE FROM reports WHERE id = %s RETURNING id", (report_id,)
            ).fetchone()
            conn.commit()
        if not deleted:
            return jsonify({"success": False, "error": "신고 내역을 찾을 수 없습니다."}), 404
        return jsonify({"success": True})

    data = request.get_json() or {}
    status = (
        data.get("status")
        if data.get("status") in {"pending", "reviewed", "closed"}
        else "reviewed"
    )
    with get_db() as conn:
        conn.execute(
            "UPDATE reports SET status = %s, handled_by = %s, handled_at = %s WHERE id = %s",
            (status, session["user_id"], now_str(), report_id),
        )
        conn.commit()
    return jsonify({"success": True})


@admin_required_api
def admin_user_suspension(user_id):
    """신고를 검토한 뒤 경고, 24시간·7일 정지, 영구 정지, 정지 해제 중 하나를 적용한다.

    관리자 계정과 본인은 대상이 될 수 없다. 처리 내역은 moderation_actions에 남기고,
    연결된 신고가 있으면 함께 '처리 완료'로 닫는다.
    """
    data = request.get_json() or {}
    try:
        action, report_id, reason = admin_service.moderation_request(
            data.get("action"), data.get("report_id"), data.get("reason")
        )
    except AdminServiceError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    # 기간 정지의 길이(초). 정지 해제 시각은 지금 시각에 이 값을 더해 저장한다.
    durations = {"24h": 24 * 60 * 60, "7d": 7 * 24 * 60 * 60}

    with get_db() as conn:
        target = conn.execute("SELECT id, is_admin FROM users WHERE id = %s", (user_id,)).fetchone()
        if not target:
            return jsonify({"success": False, "error": "사용자를 찾을 수 없습니다."}), 404
        # 관리자끼리 서로 정지하거나 자기 자신을 정지하는 사고를 막는다.
        if target["is_admin"] or user_id == session["user_id"]:
            return (
                jsonify({"success": False, "error": "관리자 계정은 정지 처리할 수 없습니다."}),
                403,
            )

        # 경고는 계정 상태를 바꾸지 않고 기록만 남긴다. 사용자는 다음 접속 때 경고를 확인하게 된다.
        if action == "warning":
            pass
        elif action == "lift":
            conn.execute(
                "UPDATE users SET is_suspended = FALSE, suspended_until = 0, suspension_reason = NULL WHERE id = %s",
                (user_id,),
            )
        elif action == "permanent":
            conn.execute(
                "UPDATE users SET is_suspended = TRUE, suspended_until = 0, suspension_reason = %s WHERE id = %s",
                (reason, user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET is_suspended = TRUE, suspended_until = %s, suspension_reason = %s WHERE id = %s",
                (time.time() + durations[action], reason, user_id),
            )
        conn.execute(
            """
            INSERT INTO moderation_actions (target_user_id, admin_user_id, action, reason, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """,
            (user_id, session["user_id"], action, reason, now_str()),
        )
        # 신고에서 시작한 처리라면, 그 신고가 실제로 이 사용자에 대한 것일 때만 '처리 완료'로 닫는다.
        if report_id and action != "lift":
            report = conn.execute(
                """
                SELECT r.id FROM reports r
                LEFT JOIN messages m ON m.id = r.message_id
                WHERE r.id = %s AND (m.sender_id = %s OR r.reported_user_id = %s)
            """,
                (report_id, user_id, user_id),
            ).fetchone()
            if report:
                conn.execute(
                    "UPDATE reports SET status = 'closed', handled_by = %s, handled_at = %s WHERE id = %s",
                    (session["user_id"], now_str(), report_id),
                )
        conn.commit()

    # 이미 열려 있는 탭도 다음 요청부터 차단된다. 실시간 연결 기록도 지워 온라인 표시가 남지 않게 하고, 화면에는 정지 안내를 띄우게 알린다.
    if action in {"24h", "7d", "permanent"}:
        with active_socket_ids_lock:
            active_socket_ids.pop(user_id, None)
        emit_safe("account_suspended", {"reason": reason}, room=f"user_{user_id}")
    return jsonify({"success": True, "action": action})


@admin_required_api
def admin_delete_user(user_id):
    """계정을 완전히 삭제한다(하드 삭제). 되돌릴 수 없다.

    메시지, 친구 관계 등 본인 소유 데이터는 DB 외래키의 ON DELETE CASCADE로 함께 지워진다.
    관리자 계정과 본인은 삭제할 수 없다.
    """
    with get_db() as conn:
        target = conn.execute("SELECT id, is_admin FROM users WHERE id = %s", (user_id,)).fetchone()
        if not target:
            return jsonify({"success": False, "error": "사용자를 찾을 수 없습니다."}), 404
        # 관리자와 본인 계정은 삭제할 수 없다.
        if target["is_admin"] or user_id == session["user_id"]:
            return jsonify({"success": False, "error": "관리자 계정은 삭제할 수 없습니다."}), 403
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

    with active_socket_ids_lock:
        active_socket_ids.pop(user_id, None)
    emit_safe("account_deleted", {}, room=f"user_{user_id}")
    return jsonify({"success": True})


# === 대화방(conversations) API ===
# URL은 blueprints/chat.py의 CHAT_ROUTES에서 연결한다.
@login_required_api
def get_conversations():
    """내 대화방 목록을 화면에 필요한 모든 정보와 함께 돌려준다(GET /api/conversations).

    숨기지 않은 대화방만 대상으로 하며, 항목마다 상대 정보(1:1) 또는 그룹 정보, 마지막 메시지 미리보기,
    읽지 않은 개수, 접속 여부, 차단 관계를 채운다. 정렬은 '고정한 방 → 최근 활동 순'이다.

    참고: 대화방마다 쿼리를 여러 번 실행하는 구조라 대화방 수에 비례해 느려진다.
    """
    user_id = session["user_id"]
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.is_group, c.name, c.profile_image, c.last_activity_id, c.chat_theme, c.is_disabled,
                   cm.last_read_message_id, cm.is_muted, cm.is_pinned
            FROM conversations c
            JOIN conversation_members cm ON cm.conversation_id = c.id
            WHERE cm.user_id = %s AND cm.hidden_at IS NULL
        """,
            (user_id,),
        ).fetchall()

        result = []
        for row in rows:
            conversation_id = row["id"]

            peer_id = None
            peer_username = None
            peer_profile_image = None
            blocked_by_me = False
            blocked_me = False

            # 그룹은 방 이름·사진을, 1:1은 상대방의 이름·프로필을 대화방의 이름과 사진으로 쓴다.
            if row["is_group"]:
                display_name = row["name"] or "그룹 채팅"
                group_profile_image = row["profile_image"] or DEFAULT_PROFILE_IMAGE
            else:
                group_profile_image = None
                peer = conn.execute(
                    """
                    SELECT users.id, users.display_name, users.username, users.profile_image, users.cover_image, users.bio FROM conversation_members
                    JOIN users ON users.id = conversation_members.user_id
                    WHERE conversation_members.conversation_id = %s AND conversation_members.user_id != %s
                """,
                    (conversation_id, user_id),
                ).fetchone()

                if peer:
                    display_name = peer["display_name"] or peer["username"]
                    peer_id = peer["id"]
                    peer_username = peer["username"]
                    peer_profile_image = peer["profile_image"]
                    blocked_by_me = (
                        conn.execute(
                            "SELECT 1 FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
                            (user_id, peer_id),
                        ).fetchone()
                        is not None
                    )
                    blocked_me = (
                        conn.execute(
                            "SELECT 1 FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
                            (peer_id, user_id),
                        ).fetchone()
                        is not None
                    )
                else:
                    display_name = "(알 수 없음)"

            last_msg = conn.execute(
                "SELECT id, text, image, video, audio, file_name, time, sent_at FROM messages WHERE conversation_id = %s ORDER BY id DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()

            message_text, last_time, last_sent_at = "", "", None
            last_msg_id = last_msg["id"] if last_msg else 0
            if last_msg:
                # 마지막 메시지가 첨부면, 목록에 보여 줄 문구를 '__종류__문구' 형태로 만든다. 앞의 표식으로 프런트가 아이콘을 고른다.
                if last_msg["audio"]:
                    message_text = "__AUDIO__음성 메시지"
                elif last_msg["file_name"]:
                    message_text = "__FILE__파일"
                elif last_msg["video"]:
                    message_text = "__VIDEO__동영상"
                elif last_msg["image"]:
                    message_text = "__CAMERA__사진"
                else:
                    message_text = last_msg["text"] or ""
                last_time = last_msg["time"] or ""
                last_sent_at = last_msg["sent_at"]

            member_count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM conversation_members WHERE conversation_id = %s",
                (conversation_id,),
            ).fetchone()
            member_count = member_count_row["cnt"] if member_count_row else 0

            # 읽지 않은 개수는 '내가 마지막으로 읽은 메시지 ID보다 큰 메시지'를 센다.
            unread_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = %s AND id > %s",
                (conversation_id, row["last_read_message_id"]),
            ).fetchone()
            unread = unread_row["cnt"] if unread_row else 0

            result.append(
                {
                    "id": conversation_id,
                    "isGroup": bool(row["is_group"]),
                    "name": display_name,
                    "message": message_text,
                    "lastTime": last_time,
                    "lastSentAt": last_sent_at,
                    "chatTheme": row["chat_theme"] or "default",
                    "isDisabled": bool(row["is_disabled"]),
                    "isMuted": bool(row["is_muted"]),
                    "isPinned": bool(row["is_pinned"]),
                    "unreadCount": unread,
                    "peerId": peer_id,
                    "peerUsername": peer_username,
                    "peerProfileImage": peer_profile_image,
                    "peerCoverImage": peer["cover_image"] if not row["is_group"] and peer else None,
                    "peerBio": peer["bio"] if not row["is_group"] and peer else "",
                    "isOnline": bool(peer_id and is_user_online(peer_id)),
                    "groupProfileImage": group_profile_image,
                    "memberCount": member_count,
                    "blockedByMe": blocked_by_me,
                    "blockedMe": blocked_me,
                    # 정렬 기준. 시스템 메시지 등도 반영하는 last_activity_id를 우선하고, 없으면 마지막 메시지 ID를 쓴다.
                    "_sortKey": row["last_activity_id"] or last_msg_id,
                }
            )
        # 고정한 방이 위로, 그 안에서는 최근 활동이 위로 오도록 내림차순 정렬한다.
        result.sort(key=lambda r: (r["isPinned"], r["_sortKey"]), reverse=True)
        return jsonify(result)


@login_required_api
def create_group_conversation():
    """새 그룹 채팅방을 만든다(POST /api/conversations). 검증과 생성은 ChatService가 맡는다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    usernames = data.get("usernames") or []

    try:
        conversation_id = chat_service.create_group(user_id, name, usernames)
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    return jsonify({"success": True, "conversationId": conversation_id})


@login_required_api
def update_conversation_theme(conversation_id):
    """채팅방 테마를 바꾸고 모든 멤버에게 알린다(PATCH .../theme).

    테마는 대화방 공용 설정이라, 바꾼 사람과 새 테마 이름을 시스템 메시지로 남긴다.
    """
    theme = (request.get_json() or {}).get("theme", "default")
    user_id = session["user_id"]
    # 시스템 메시지에 보여 줄 한글 테마 이름. 목록에 없는 값은 그대로 쓴다(검증은 ChatService가 한다).
    theme_name = {
        "default": "기본",
        "heart": "하트",
        "teddy": "테디베어",
        "glass": "글라스",
        "aurora": "오로라",
        "mono": "모노",
        "spring": "봄",
        "summer": "여름",
        "autumn": "가을",
        "winter": "겨울",
        "christmas": "크리스마스",
        "halloween": "할로윈",
    }.get(theme, theme)
    try:
        chat_service.update_theme(
            conversation_id,
            user_id,
            theme,
            # 서비스가 같은 트랜잭션 안에서 시스템 메시지를 남길 수 있도록 만드는 콜백.
            lambda conn, conv_id, name, actor_id: create_system_message(
                conn, conv_id, f"{name}님이 {theme_name} 테마로 변경했습니다.", actor_id
            ),
        )
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
    return jsonify({"success": True, "theme": theme})


@login_required_api
def update_conversation_preferences(conversation_id):
    """채팅방 고정·알림 끄기를 저장한다(PATCH .../preferences). 사용자별 설정이라 멤버십 테이블에만 기록한다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    try:
        updated = chat_service.update_preferences(
            conversation_id,
            user_id,
            is_muted=bool(data["is_muted"]) if "is_muted" in data else None,
            is_pinned=bool(data["is_pinned"]) if "is_pinned" in data else None,
        )
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    if not updated:
        return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404
    return jsonify({"success": True})


@login_required_api
def rename_group_conversation(conversation_id):
    """그룹 이름을 바꾸고 멤버들에게 알린다(PATCH .../name). 방장만 가능하다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    new_name = (data.get("name") or "").strip()

    try:
        chat_service.rename_group(conversation_id, user_id, new_name)
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )

    return jsonify({"success": True, "name": new_name})


@login_required_api
def leave_conversation(conversation_id):
    """대화방에서 나간다(DELETE .../leave).

    마지막 멤버가 나가 방이 삭제되면 그 방에 있던 이미지 파일도 함께 지운다.
    """
    user_id = session["user_id"]
    try:
        result = chat_service.leave_conversation(
            conversation_id,
            user_id,
            lambda conn, conv_id, name, actor_id: create_system_message(
                conn, conv_id, f"{name}님이 나갔습니다.", actor_id
            ),
        )
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    # 방이 지워졌다면 알릴 멤버가 더 없으므로 이미지 파일만 정리하고 끝낸다.
    if result.conversation_deleted:
        for image_path in result.image_paths:
            delete_image_file(image_path)
        return jsonify({"success": True})

    with get_db() as conn:
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
    return jsonify({"success": True})


@login_required_api
def disable_group_conversation(conversation_id):
    """방장이 그룹 채팅을 종료한다(POST .../disable). 이전 대화는 볼 수 있지만 새 메시지는 보낼 수 없다."""
    user_id = session["user_id"]
    try:
        chat_service.disable_group(
            conversation_id,
            user_id,
            lambda conn, conv_id, name, actor_id: create_system_message(
                conn,
                conv_id,
                f"{name}님이 그룹 채팅을 종료했습니다. 이전 대화는 계속 볼 수 있습니다.",
                actor_id,
            ),
        )
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
    return jsonify({"success": True})


@login_required_api
def hide_conversation(conversation_id):
    """내 목록에서만 대화방을 숨긴다(POST .../hide). 새 메시지가 오면 다시 나타난다."""
    user_id = session["user_id"]
    if not chat_service.hide_conversation(conversation_id, user_id):
        return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404
    return jsonify({"success": True})


@login_required_api
def get_conversation_members(conversation_id):
    """그룹 멤버 목록과 방장·그룹 사진 정보를 돌려준다(GET .../members). 멤버만 볼 수 있다."""
    user_id = session["user_id"]
    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conv = conn.execute(
            "SELECT owner_id, profile_image FROM conversations WHERE id = %s", (conversation_id,)
        ).fetchone()
        owner_id = conv["owner_id"] if conv else None
        group_profile_image = conv["profile_image"] if conv else None

        rows = conn.execute(
            """
            SELECT users.id, users.username, users.display_name, users.profile_image
            FROM conversation_members
            JOIN users ON users.id = conversation_members.user_id
            WHERE conversation_members.conversation_id = %s
        """,
            (conversation_id,),
        ).fetchall()

        members = [
            {
                "id": row["id"],
                "username": row["username"],
                "name": row["display_name"] or row["username"],
                "profileImage": row["profile_image"],
            }
            for row in rows
        ]

    return jsonify(
        {
            "success": True,
            "members": members,
            "ownerId": owner_id,
            "groupProfileImage": group_profile_image,
        }
    )


@login_required_api
def invite_conversation_members(conversation_id):
    """그룹에 멤버를 초대한다(POST .../members). 멤버들의 친구·대화 목록을 갱신하도록 알린다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    usernames = data.get("usernames") or []

    try:
        chat_service.invite_members(conversation_id, user_id, usernames)
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    with get_db() as conn:
        broadcast_to_conversation(conn, conversation_id, "friend_updated", {})

    return jsonify({"success": True})


@login_required_api
def remove_conversation_member(conversation_id, member_user_id):
    """방장이 멤버를 내보낸다(DELETE .../members/<id>). 내보낸 사용자 화면도 바로 갱신되게 알린다."""
    user_id = session["user_id"]
    try:
        chat_service.remove_member(conversation_id, user_id, member_user_id)
    except ChatServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    with get_db() as conn:
        notify_user(member_user_id, "friend_updated", {})
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )

    return jsonify({"success": True})


# === 메시지 API ===
@login_required_api
def link_preview():
    """메시지 안 링크의 미리보기 정보(제목·설명·이미지)를 돌려준다(POST /api/link-preview)."""
    url = (request.get_json() or {}).get("url", "").strip()
    preview = get_link_preview(url)
    return jsonify({"success": bool(preview), "preview": preview})


@login_required_api
def get_messages(conversation_id):
    """대화방의 모든 메시지를 오래된 순서로 돌려준다(GET .../messages). 멤버만 볼 수 있다.

    메시지마다 '아직 읽지 않은 사람 수'를 계산해 넣는다(보낸 사람 제외, 마지막으로 읽은 메시지 ID가 더 작은 멤버).
    그룹 채팅에는 보낸 사람의 이름·프로필 사진도 함께 담는다.
    """
    user_id = session["user_id"]
    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conv = conn.execute(
            "SELECT is_group FROM conversations WHERE id = %s", (conversation_id,)
        ).fetchone()

        member_read_rows = conn.execute(
            "SELECT user_id, last_read_message_id FROM conversation_members WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchall()
        # 멤버별 '마지막으로 읽은 메시지 ID'. 아래에서 메시지마다 안 읽은 사람 수를 세는 데 쓴다.
        member_last_read = {m["user_id"]: m["last_read_message_id"] for m in member_read_rows}

        sender_names = {}
        sender_images = {}
        # 그룹 채팅에서만 메시지마다 보낸 사람의 이름·사진을 보여 주므로, 이때만 멤버 정보를 조회한다.
        if conv and conv["is_group"]:
            member_rows = conn.execute(
                """
                SELECT users.id, users.display_name, users.username, users.profile_image FROM conversation_members
                JOIN users ON users.id = conversation_members.user_id
                WHERE conversation_members.conversation_id = %s       
            """,
                (conversation_id,),
            ).fetchall()
            sender_names = {m["id"]: (m["display_name"] or m["username"]) for m in member_rows}
            sender_images = {m["id"]: m["profile_image"] for m in member_rows}

        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = %s ORDER BY id ASC", (conversation_id,)
        ).fetchall()

        messages = []
        for row in rows:
            # 보낸 사람을 뺀 멤버 중, 이 메시지를 아직 읽지 않은 사람 수(화면의 '안 읽은 사람' 숫자).
            unread_count = sum(
                1
                for uid, last_read in member_last_read.items()
                if uid != row["sender_id"] and last_read < row["id"]
            )
            messages.append(
                {
                    "id": row["id"],
                    "senderId": row["sender_id"],
                    "senderName": sender_names.get(row["sender_id"]),
                    "senderProfileImage": sender_images.get(row["sender_id"]),
                    "mine": row["sender_id"] == user_id,
                    "text": row["text"],
                    "image": row["image"],
                    "video": row["video"],
                    "audio": row["audio"],
                    "messageType": row["message_type"] or "user",
                    "filePath": row["file_path"],
                    "fileName": row["file_name"],
                    "fileSize": row["file_size"],
                    "time": row["time"],
                    "date": row["date"],
                    "sentAt": row["sent_at"],
                    "reply": json.loads(row["reply"]) if row["reply"] else None,
                    "edited": bool(row["edited"]),
                    "pinned": bool(row["pinned"]),
                    "reactions": json.loads(row["reactions"]) if row["reactions"] else [],
                    "unreadCount": unread_count,
                }
            )
        return jsonify(messages)


@login_required_api
def send_message(conversation_id):
    """텍스트 메시지를 보낸다(POST .../messages).

    처리 순서: 입력 검증 → 멤버 확인 → 종료된 방인지 확인 → 차단 확인 → 저장 → 읽음 위치·최근 활동 갱신
    → 푸시 알림 → 실시간 갱신 알림. 사진·동영상·파일·음성은 아래의 별도 라우트가 맡는다.
    """
    user_id = session["user_id"]
    data = request.get_json() or {}
    reply = data.get("reply")

    # 이 라우트는 텍스트 전용이다. 클라이언트의 trim() 검사는 콘솔이나 직접 API 호출로 우회할 수 있으므로 서버에서도 반드시 검증한다.
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "메시지 내용을 입력해주세요."}), 400
    if len(text) > 5000:
        return jsonify({"success": False, "error": "메시지는 5,000자 이하로 입력해주세요."}), 400

    with get_db() as conn:
        # 멤버가 아니면 방이 있는지 여부도 알려 주지 않도록 '없는 방'과 같은 404로 응답한다.
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        # 방장이 종료한 그룹 채팅에는 새 메시지를 보낼 수 없다.
        if conversation_is_disabled(conn, conversation_id):
            return (
                jsonify(
                    {"success": False, "error": "종료된 채팅방에서는 새 메시지를 보낼 수 없습니다."}
                ),
                403,
            )

        # 1:1 대화에서 어느 한쪽이라도 차단했다면 메시지를 주고받을 수 없다.
        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return (
                jsonify(
                    {"success": False, "error": "차단된 사용자와는 메시지를 주고받을 수 없습니다."}
                ),
                403,
            )

        # 기준 시각(UTC 밀리초)을 한 번 정하고, 같은 값으로 호환용 시간 문자열도 만든다.
        sent_at = current_message_timestamp_ms()
        time_label, date_label = legacy_message_labels(sent_at)
        msg_row = conn.execute(
            """
            INSERT INTO messages (conversation_id, sender_id, text, image, time, date, sent_at, reply, edited, pinned, reactions)
            VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, FALSE, FALSE, %s) RETURNING id
        """,
            (
                conversation_id,
                user_id,
                text,
                time_label,
                date_label,
                sent_at,
                json.dumps(reply) if reply else None,
                json.dumps([]),
            ),
        ).fetchone()
        new_message_id = msg_row["id"]

        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            # 보낸 사람의 읽음 위치를 방금 보낸 메시지로 옮긴다(내 메시지는 읽은 것으로 본다).
            (new_message_id, conversation_id, user_id),
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id),
        )

        # 상대가 이 대화방을 숨겨 뒀다면 새 메시지로 다시 나타나게 한다.
        unhide_conversation(conn, conversation_id)

        conn.commit()
        # DB 반영(commit)이 끝난 뒤에 알림을 보낸다. 푸시에는 본문 앞 120자만 싣는다.
        notify_conversation_message(conn, conversation_id, user_id, text[:120])
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
        return jsonify({"success": True})


@login_required_api
def send_image(conversation_id):
    """사진 메시지를 보낸다(POST .../messages/image). 사진은 data URL(base64)로 받아 검증한 뒤 저장한다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    image_data_url = data.get("image")

    if not image_data_url or not image_data_url.startswith("data:image"):
        return jsonify({"success": False, "error": "올바른 이미지 데이터가 아닙니다."}), 400

    # 주의: 이미지를 먼저 저장하고 아래에서 멤버·차단 여부를 확인한다. 권한이 없어 거부되는 경우에도 저장된 파일이 남는다(순서 개선 필요).
    image_path = save_base64_image(image_data_url)
    if not image_path:
        return jsonify({"success": False, "error": "이미지 처리 중 오류가 발생했습니다."}), 400

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        if conversation_is_disabled(conn, conversation_id):
            return (
                jsonify(
                    {"success": False, "error": "종료된 채팅방에서는 사진을 보낼 수 없습니다."}
                ),
                403,
            )

        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return (
                jsonify(
                    {"success": False, "error": "차단된 사용자와는 메시지를 주고받을 수 없습니다."}
                ),
                403,
            )

        sent_at = current_message_timestamp_ms()
        time_label, date_label = legacy_message_labels(sent_at)
        msg_row = conn.execute(
            """
            INSERT INTO messages (conversation_id, sender_id, text, image, time, date, sent_at, reply, edited, pinned, reactions)
            VALUES (%s, %s, NULL, %s, %s, %s, %s, NULL, FALSE, FALSE, %s) RETURNING id
        """,
            (conversation_id, user_id, image_path, time_label, date_label, sent_at, json.dumps([])),
        ).fetchone()
        new_message_id = msg_row["id"]

        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            (new_message_id, conversation_id, user_id),
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id),
        )

        unhide_conversation(conn, conversation_id)

        conn.commit()
        notify_conversation_message(conn, conversation_id, user_id, "사진을 보냈습니다.")
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
    return jsonify({"success": True, "image": image_path})


# 채팅에서 보낼 수 있는 동영상 확장자.
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}


def is_allowed_video(filename):
    """파일 이름의 확장자가 허용된 동영상 형식인지 확인한다."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


@login_required_api
def send_video(conversation_id):
    """동영상 메시지를 보낸다(POST .../messages/video). 형식(mp4·webm·mov)과 크기(20MB)를 검사한 뒤 저장한다."""
    user_id = session["user_id"]

    video_file = request.files.get("video")
    if video_file:
        # 파일 끝으로 이동해 크기를 잰 뒤 처음으로 되돌린다. 전체를 메모리로 읽지 않고도 크기를 알 수 있다.
        video_file.seek(0, os.SEEK_END)
        video_size = video_file.tell()
        video_file.seek(0)
        if video_size > CHAT_FILE_MAX_BYTES:
            return jsonify({"success": False, "error": "동영상 파일이 너무 큽니다."}), 400
    if not video_file or video_file.filename == "":
        return jsonify({"success": False, "error": "동영상 파일이 없습니다."}), 400

    if not is_allowed_video(video_file.filename):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "지원하지 않는 동영상 형식입니다 (mp4, webm, mov만 가능).",
                }
            ),
            400,
        )

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        if conversation_is_disabled(conn, conversation_id):
            return (
                jsonify(
                    {"success": False, "error": "종료된 채팅방에서는 동영상을 보낼 수 없습니다."}
                ),
                403,
            )

        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return (
                jsonify(
                    {"success": False, "error": "차단된 사용자와는 메시지를 주고받을 수 없습니다."}
                ),
                403,
            )

        # 권한 검사를 모두 통과한 뒤에만 파일을 저장한다.
        video_path, _ = save_uploaded_file(video_file, "videos")
        if not video_path:
            return jsonify({"success": False, "error": "동영상 저장에 실패했습니다."}), 500

        sent_at = current_message_timestamp_ms()
        time_label, date_label = legacy_message_labels(sent_at)
        msg_row = conn.execute(
            """
            INSERT INTO messages (conversation_id, sender_id, text, image, video, time, date, sent_at, reply, edited, pinned, reactions)
            VALUES (%s, %s, NULL, NULL, %s, %s, %s, %s, NULL, FALSE, FALSE, %s) RETURNING id
        """,
            (conversation_id, user_id, video_path, time_label, date_label, sent_at, json.dumps([])),
        ).fetchone()
        new_message_id = msg_row["id"]

        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            (new_message_id, conversation_id, user_id),
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id),
        )

        unhide_conversation(conn, conversation_id)

        conn.commit()
        notify_conversation_message(conn, conversation_id, user_id, "동영상을 보냈습니다.")
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
    return jsonify({"success": True, "video": video_path})


@login_required_api
def send_file(conversation_id):
    """문서·압축 파일 등을 보낸다(POST .../messages/file). 허용 확장자와 크기(20MB)를 검사한 뒤 저장한다."""
    user_id = session["user_id"]
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "파일을 선택해주세요."}), 400

    # 확장자는 파일 이름 마지막 점 뒤의 값을 소문자로 비교한다.
    extension = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    if extension not in CHAT_FILE_EXTENSIONS:
        return jsonify({"success": False, "error": "지원하지 않는 파일 형식입니다."}), 400
    upload.seek(0, os.SEEK_END)
    size = upload.tell()
    upload.seek(0)
    if size > CHAT_FILE_MAX_BYTES:
        return jsonify({"success": False, "error": "파일은 20MB 이하만 보낼 수 있습니다."}), 400

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404
        if conversation_is_disabled(conn, conversation_id):
            return (
                jsonify(
                    {"success": False, "error": "종료된 채팅방에서는 파일을 보낼 수 없습니다."}
                ),
                403,
            )
        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return (
                jsonify(
                    {"success": False, "error": "차단된 사용자에게는 파일을 보낼 수 없습니다."}
                ),
                403,
            )

    # 권한 검사용 DB 연결은 위에서 닫고, 오래 걸릴 수 있는 파일 저장은 연결 없이 한다(연결 풀을 오래 점유하지 않기 위해).
    file_path, file_name = save_uploaded_file(upload, "files")
    if not file_path:
        return jsonify({"success": False, "error": "파일 저장에 실패했습니다."}), 500

    with get_db() as conn:
        sent_at = current_message_timestamp_ms()
        time_label, date_label = legacy_message_labels(sent_at)
        row = conn.execute(
            """
            INSERT INTO messages (conversation_id, sender_id, text, image, video, file_path, file_name, file_size, time, date, sent_at, reply, edited, pinned, reactions)
            VALUES (%s, %s, NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, NULL, FALSE, FALSE, %s) RETURNING id
        """,
            (
                conversation_id,
                user_id,
                file_path,
                file_name,
                size,
                time_label,
                date_label,
                sent_at,
                json.dumps([]),
            ),
        ).fetchone()
        new_message_id = row["id"]
        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            (new_message_id, conversation_id, user_id),
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id),
        )
        unhide_conversation(conn, conversation_id)
        conn.commit()
        notify_conversation_message(conn, conversation_id, user_id, f"파일: {file_name}")
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
    return jsonify({"success": True, "filePath": file_path, "fileName": file_name})


@login_required_api
def send_audio(conversation_id):
    """음성 메시지를 보낸다(POST .../messages/audio). 형식(webm·ogg·mp4·m4a)과 길이(최대 30초)를 검사한다.

    길이는 클라이언트가 보낸 duration 값을 믿고 검사하므로, 서버에서 파일을 직접 분석한 값은 아니다.
    """
    user_id = session["user_id"]
    audio_file = request.files.get("audio")
    if not audio_file or not audio_file.filename:
        return jsonify({"success": False, "error": "음성 파일을 찾을 수 없습니다."}), 400
    # 브라우저가 녹음해서 보내는 형식(MediaRecorder)만 허용한다.
    if os.path.splitext(audio_file.filename)[1].lower() not in {".webm", ".ogg", ".mp4", ".m4a"}:
        return jsonify({"success": False, "error": "지원하지 않는 음성 형식입니다."}), 400
    try:
        duration = float(request.form.get("duration", "0"))
    except ValueError:
        duration = 0
    # 음성 메시지는 최대 30초. duration이 없거나 숫자가 아니면 0으로 보고 거부한다.
    if duration <= 0 or duration > 30:
        return (
            jsonify({"success": False, "error": "음성 메시지는 최대 30초까지 보낼 수 있습니다."}),
            400,
        )
    with get_db() as conn:
        # 음성은 멤버가 아니거나 종료된 방이면 같은 오류 하나로 처리한다.
        if not get_membership(conn, conversation_id, user_id) or conversation_is_disabled(
            conn, conversation_id
        ):
            return (
                jsonify(
                    {"success": False, "error": "이 채팅방에는 음성 메시지를 보낼 수 없습니다."}
                ),
                403,
            )
        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "차단된 사용자에게는 음성 메시지를 보낼 수 없습니다.",
                    }
                ),
                403,
            )
    # 권한 검사용 연결은 닫고, 파일 저장을 한 뒤 새 연결로 메시지를 기록한다.
    audio_path, _ = save_uploaded_file(audio_file, "audio")
    if not audio_path:
        return jsonify({"success": False, "error": "음성 메시지 저장에 실패했습니다."}), 500
    with get_db() as conn:
        sent_at = current_message_timestamp_ms()
        time_label, date_label = legacy_message_labels(sent_at)
        row = conn.execute(
            """
            INSERT INTO messages (conversation_id, sender_id, audio, time, date, sent_at, edited, pinned, reactions)
            VALUES (%s, %s, %s, %s, %s, %s, FALSE, FALSE, %s) RETURNING id
        """,
            (conversation_id, user_id, audio_path, time_label, date_label, sent_at, json.dumps([])),
        ).fetchone()
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (row["id"], conversation_id),
        )
        unhide_conversation(conn, conversation_id)
        conn.commit()
        notify_conversation_message(conn, conversation_id, user_id, "음성 메시지를 보냈습니다.")
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
    return jsonify({"success": True, "audio": audio_path})


@login_required_api
def forward_message(message_id):
    """메시지를 내가 속한 다른 대화방으로 전달한다(POST /api/messages/<id>/forward). 받은 대화방 멤버들에게 갱신을 알린다."""
    user_id = session["user_id"]
    target_conversation_id = (request.get_json() or {}).get("conversation_id")
    try:
        target_conversation_id = message_service.forward_message(
            message_id, user_id, target_conversation_id
        )
    except MessageServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn,
            target_conversation_id,
            "conversation_updated",
            {"conversationId": target_conversation_id},
        )
    return jsonify({"success": True})


@login_required_api
def report_message(message_id):
    """메시지를 신고한다(POST /api/messages/<id>/report). 사유 검증과 저장은 MessageService가 맡는다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip()
    detail = (data.get("detail") or "").strip()
    try:
        message_service.report_message(message_id, user_id, reason, detail)
    except MessageServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code
    return jsonify({"success": True, "message": "신고가 접수되었습니다."})


@app.route("/api/users/<int:user_id>/report", methods=["POST"])
@login_required_api
def report_user(user_id):
    """프로필에서 특정 메시지가 아니라 사용자 자체를 신고한다. 같은 사용자를 중복 신고해도 한 건만 남는다."""
    reporter_id = session["user_id"]
    if user_id == reporter_id:
        return jsonify({"success": False, "error": "본인은 신고할 수 없습니다."}), 400
    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip()
    detail = (data.get("detail") or "").strip()
    # 신고 사유 목록은 MessageService.REPORT_REASONS와 같아야 한다.
    if reason not in {"스팸", "욕설·괴롭힘", "부적절한 콘텐츠", "사칭", "기타"}:
        return jsonify({"success": False, "error": "신고 사유를 선택해주세요."}), 400
    if len(detail) > 1000:
        return jsonify({"success": False, "error": "신고 내용은 1,000자 이하로 입력해주세요."}), 400
    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id = %s", (user_id,)).fetchone()
        if not target:
            return jsonify({"success": False, "error": "사용자를 찾을 수 없습니다."}), 404
        conn.execute(
            """INSERT INTO reports (reporter_id, reported_user_id, reason, detail, created_at)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (reporter_id, reported_user_id) WHERE reported_user_id IS NOT NULL DO NOTHING""",
            (reporter_id, user_id, reason, detail or None, now_str()),
        )
        conn.commit()
    return jsonify({"success": True, "message": "신고가 접수되었습니다."})


@login_required_api
def edit_message(message_id):
    """내 메시지의 본문을 수정한다(PATCH /api/messages/<id>). 대화방 멤버들 화면을 갱신하도록 알린다."""
    user_id = session["user_id"]
    data = request.get_json() or {}

    text = (data.get("text") or "").strip()
    try:
        conversation_id = message_service.edit_message(message_id, user_id, text)
    except MessageServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn,
            conversation_id,
            "conversation_updated",
            {"conversationId": conversation_id},
        )
    return jsonify({"success": True})


@login_required_api
def delete_message(message_id):
    """내 메시지를 삭제한다(DELETE /api/messages/<id>). 첨부 이미지가 있었다면 DB 삭제 뒤에 파일도 지운다."""
    user_id = session["user_id"]

    try:
        conversation_id, image_path = message_service.delete_message(message_id, user_id)
    except MessageServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn,
            conversation_id,
            "conversation_updated",
            {"conversationId": conversation_id},
        )

    # 메시지 행을 먼저 지우고(서비스), 그 뒤에 파일을 정리한다. 이미지가 없으면 함수가 아무 일도 하지 않는다.
    delete_image_file(image_path)
    return jsonify({"success": True})


@login_required_api
def pin_message(message_id):
    """메시지를 상단에 고정하거나 고정을 푼다(POST /api/messages/<id>/pin)."""
    user_id = session["user_id"]

    try:
        conversation_id, now_pinned = message_service.toggle_pin(message_id, user_id)
    except MessageServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn,
            conversation_id,
            "conversation_updated",
            {"conversationId": conversation_id},
        )
    return jsonify({"success": True, "pinned": now_pinned})


@login_required_api
def react_message(message_id):
    """메시지에 이모지 반응을 달거나 취소한다(POST /api/messages/<id>/react)."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    emoji = data.get("emoji")

    try:
        conversation_id, reactions = message_service.toggle_reaction(message_id, user_id, emoji)
    except MessageServiceError as error:
        return jsonify({"success": False, "error": str(error)}), error.status_code

    with get_db() as conn:
        broadcast_to_conversation(
            conn,
            conversation_id,
            "conversation_updated",
            {"conversationId": conversation_id},
        )
    return jsonify({"success": True, "reactions": reactions})


@app.route("/api/account/cover-image", methods=["PATCH", "DELETE"])
@login_required_api
def account_cover_image():
    """내 프로필 배경 사진을 바꾸거나(PATCH) 지운다(DELETE).

    새 사진이 저장된 뒤에 이전 파일을 지워서, 저장에 실패해도 기존 사진은 남는다.
    """
    user_id = session["user_id"]
    with get_db() as conn:
        current = conn.execute("SELECT cover_image FROM users WHERE id = %s", (user_id,)).fetchone()
        old_image = current["cover_image"] if current else None
        if request.method == "DELETE":
            conn.execute("UPDATE users SET cover_image = NULL WHERE id = %s", (user_id,))
            new_path = None
        else:
            image_data = (request.get_json() or {}).get("image")
            if not image_data or not image_data.startswith("data:image"):
                return jsonify({"success": False, "error": "올바른 이미지 데이터가 아닙니다."}), 400
            new_path = save_base64_image(image_data)
            if not new_path:
                return jsonify({"success": False, "error": "배경사진 저장에 실패했습니다."}), 500
            conn.execute("UPDATE users SET cover_image = %s WHERE id = %s", (new_path, user_id))
        recipient_ids = profile_update_recipient_ids(conn, user_id)
        conn.commit()
    notify_profile_updated(recipient_ids, user_id)
    # 이전 배경 사진 파일을 지운다. 새 경로와 같으면 방금 저장한 파일이므로 지우지 않는다.
    if old_image and old_image != new_path:
        delete_image_file(old_image)
    return jsonify({"success": True, "cover_image": new_path})


@app.route("/api/users/<int:user_id>/profile", methods=["GET"])
@login_required_api
def public_profile(user_id):
    """다른 사용자의 프로필 카드 정보를 돌려준다. 공개 범위·정지 여부를 확인하고, 볼 수 없으면 '없는 사용자'와 같은 404를 준다."""
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, display_name, username, profile_image, cover_image, bio, profile_visibility, is_suspended FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()
        if not can_view_profile(conn, session["user_id"], user):
            return (
                jsonify(
                    {"success": False, "error": "사용자를 찾을 수 없거나 비공개 프로필입니다."}
                ),
                404,
            )
    profile = dict(user)
    # 정지 여부는 접근 판단에만 쓰고 응답에는 담지 않는다.
    profile.pop("is_suspended", None)
    return jsonify({"success": True, **profile, "is_online": is_user_online(user_id)})


@app.route("/api/users/search", methods=["GET"])
@login_required_api
def search_user_profile():
    """아이디로 사용자를 찾아 프로필 카드 정보와 친구 여부를 돌려준다.

    아이디를 정확히 입력해야 하며(부분 검색 없음), 비공개 프로필은 존재 여부를 알 수 없게 404로 응답한다.
    """
    username = (request.args.get("username") or "").strip().lower()
    # 아이디 규칙(영문 소문자·숫자 5자 이상)과 같은 형식만 검색한다. 부분 검색으로 계정을 훑어보는 것을 막는다.
    if not re.fullmatch(r"[a-z0-9]{5,}", username):
        return jsonify({"success": False, "error": "아이디를 정확히 입력해주세요."}), 400
    with get_db() as conn:
        user = conn.execute(
            """
            SELECT id, display_name, username, profile_image, cover_image, bio, profile_visibility, is_suspended
            FROM users WHERE username = %s
        """,
            (username,),
        ).fetchone()
        if not can_view_profile(conn, session["user_id"], user):
            return (
                jsonify(
                    {"success": False, "error": "사용자를 찾을 수 없거나 비공개 프로필입니다."}
                ),
                404,
            )
        is_friend = are_users_friends(conn, session["user_id"], user["id"])
    profile = dict(user)
    profile.pop("is_suspended", None)
    return jsonify(
        {
            "success": True,
            "user": {**profile, "is_friend": is_friend, "is_online": is_user_online(user["id"])},
        }
    )


# === 계정 설정 API ===
# (아이디·비밀번호·프로필 사진·계정 삭제)
@app.route("/api/account/username", methods=["PATCH"])
@login_required_api
def update_username():
    """내 아이디를 바꾼다(PATCH /api/account/username). 현재 비밀번호를 한 번 더 확인한다.

    새 아이디는 영문 소문자·숫자 5자 이상이어야 하고 다른 계정과 겹치면 안 된다.
    """
    user_id = session["user_id"]
    data = request.get_json() or {}
    new_username = (data.get("new_username") or "").strip()
    current_password = data.get("current_password") or ""

    if not re.fullmatch(r"[a-z0-9]{5,}", new_username):
        return jsonify(
            {
                "success": False,
                "error": "아이디는 영어 소문자와 숫자 조합으로 5자 이상이어야 합니다.",
            }
        )

    with get_db() as conn:
        # 계정을 바꾸는 민감한 작업은 로그인 상태만으로 허용하지 않고, 현재 비밀번호를 다시 확인한다.
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"success": False, "error": "현재 비밀번호가 일치하지 않습니다."})

        # 나를 제외하고 같은 아이디를 쓰는 계정이 있는지 확인한다.
        existing = conn.execute(
            "SELECT id FROM users WHERE username = %s AND id != %s", (new_username, user_id)
        ).fetchone()
        if existing:
            return jsonify({"success": False, "error": "이미 사용 중인 아이디입니다."})

        conn.execute("UPDATE users SET username = %s WHERE id = %s", (new_username, user_id))
        conn.commit()

    session["username"] = new_username
    return jsonify({"success": True, "username": new_username})


@app.route("/api/account/password", methods=["PATCH"])
@login_required_api
def update_password():
    """내 비밀번호를 바꾼다(PATCH /api/account/password). 현재 비밀번호 확인과 새 비밀번호 정책(PasswordPolicy)을 모두 통과해야 한다.
    """
    user_id = session["user_id"]
    data = request.get_json() or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    password_confirmation = (
        data.get("password_confirmation") or data.get("new_password_confirmation") or ""
    )

    # 확인 입력이 함께 온 경우에만 일치 여부를 검사한다.
    if password_confirmation and new_password != password_confirmation:
        return jsonify({"success": False, "error": "비밀번호 확인이 일치하지 않습니다."}), 400

    if not PasswordPolicy.is_valid(new_password):
        return jsonify({"success": False, "error": PasswordPolicy.error_message()})

    with get_db() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"success": False, "error": "현재 비밀번호가 일치하지 않습니다."})

        # 토큰을 새로 발급해 다른 기기의 로그인은 끊고, 지금 세션만 새 토큰으로 유지한다.
        new_session_token = secrets.token_urlsafe(32)
        conn.execute(
            "UPDATE users SET password_hash = %s, session_token = %s WHERE id = %s",
            (generate_password_hash(new_password), new_session_token, user_id),
        )
        conn.commit()
    session["session_token"] = new_session_token

    return jsonify({"success": True})


@app.route("/api/account", methods=["DELETE"])
@login_required_api
def delete_account():
    """내 계정을 삭제한다(DELETE /api/account). 비밀번호를 다시 확인한다.

    메시지·친구 관계 등은 DB 외래키(ON DELETE CASCADE)로 함께 지워지므로, 지우기 전에 내가 보낸 이미지 목록을 먼저 모아 두고
    DB 삭제가 끝난 뒤에 실제 파일을 정리한다.
    """
    user_id = session["user_id"]
    data = request.get_json() or {}
    password = data.get("password") or ""

    with get_db() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], password):
            return jsonify({"success": False, "error": "비밀번호가 일치하지 않습니다."})

        # 계정을 지우면 메시지도 함께 사라진다. 그 전에 내가 보낸 이미지 경로를 모아 둬야 파일을 정리할 수 있다.
        image_rows = conn.execute(
            "SELECT image FROM messages WHERE sender_id = %s AND image IS NOT NULL", (user_id,)
        ).fetchall()

        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

    # DB 삭제가 확정된 뒤에 파일을 지운다. 순서가 반대면 삭제가 실패했을 때 파일만 사라진다.
    for row in image_rows:
        delete_image_file(row["image"])

    session.clear()
    return jsonify({"success": True})


@app.route("/api/account/profile-image", methods=["PATCH"])
@login_required_api
def update_profile_image():
    """내 프로필 사진을 바꾼다(PATCH /api/account/profile-image). 대화 상대 화면도 갱신되게 알리고 이전 사진 파일은 지운다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    image_data_url = data.get("image")

    if not image_data_url or not image_data_url.startswith("data:image"):
        return jsonify({"success": False, "error": "올바른 이미지 데이터가 아닙니다."}), 400

    new_path = save_base64_image(image_data_url)
    if not new_path:
        return jsonify({"success": False, "error": "이미지 처리 중 오류가 발생했습니다."}), 400

    with get_db() as conn:
        old = conn.execute("SELECT profile_image FROM users WHERE id = %s", (user_id,)).fetchone()
        conn.execute("UPDATE users SET profile_image = %s WHERE id = %s", (new_path, user_id))
        recipient_ids = profile_update_recipient_ids(conn, user_id)
        conn.commit()
    notify_profile_updated(recipient_ids, user_id)

    # 기본 이미지는 모두가 함께 쓰는 정적 파일이라 지우지 않는다.
    if old and old["profile_image"] and old["profile_image"] != DEFAULT_PROFILE_IMAGE:
        delete_image_file(old["profile_image"])

    # 화면 렌더링에 쓰는 세션의 프로필 사진도 함께 바꾼다.
    session["profile_image"] = new_path
    return jsonify({"success": True, "profile_image": new_path})


@app.route("/api/account/profile-image", methods=["DELETE"])
@login_required_api
def delete_profile_image():
    """내 프로필 사진을 지우고 기본 이미지로 되돌린다(DELETE /api/account/profile-image)."""
    user_id = session["user_id"]

    with get_db() as conn:
        user = conn.execute("SELECT profile_image FROM users WHERE id = %s", (user_id,)).fetchone()
        conn.execute(
            "UPDATE users SET profile_image = %s WHERE id = %s", (DEFAULT_PROFILE_IMAGE, user_id)
        )
        recipient_ids = profile_update_recipient_ids(conn, user_id)
        conn.commit()
    notify_profile_updated(recipient_ids, user_id)

    if user and user["profile_image"] and user["profile_image"] != DEFAULT_PROFILE_IMAGE:
        delete_image_file(user["profile_image"])

    session["profile_image"] = DEFAULT_PROFILE_IMAGE
    return jsonify({"success": True, "profile_image": DEFAULT_PROFILE_IMAGE})


@login_required_api
def update_group_photo(conversation_id):
    """그룹 채팅 사진을 바꾼다(PATCH .../photo). 방장만 가능하며 종료된 그룹은 바꿀 수 없다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    image_data_url = data.get("image")

    if not image_data_url or not image_data_url.startswith("data:image"):
        return jsonify({"success": False, "error": "올바른 이미지 데이터가 아닙니다."}), 400

    new_path = save_base64_image(image_data_url)
    if not new_path:
        return jsonify({"success": False, "error": "이미지 처리 중 오류가 발생했습니다."}), 400

    with get_db() as conn:
        conv = conn.execute(
            "SELECT is_group, owner_id, profile_image, is_disabled FROM conversations WHERE id = %s",
            (conversation_id,),
        ).fetchone()
        # 그룹 채팅이 아니면 사진을 바꿀 수 없다(1:1은 상대의 프로필 사진을 쓴다).
        if not conv or not conv["is_group"]:
            return jsonify({"success": False, "error": "그룹 채팅만 사진을 바꿀 수 있습니다."}), 400
        if conv["owner_id"] != user_id:
            return jsonify({"success": False, "error": "방장만 그룹 사진을 바꿀 수 있습니다."}), 403
        if conv["is_disabled"]:
            return (
                jsonify(
                    {"success": False, "error": "종료된 그룹 채팅방은 정보를 변경할 수 없습니다."}
                ),
                403,
            )

        old_image = conv["profile_image"]
        conn.execute(
            "UPDATE conversations SET profile_image = %s WHERE id = %s", (new_path, conversation_id)
        )
        conn.commit()
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )

    if old_image and old_image != DEFAULT_PROFILE_IMAGE:
        delete_image_file(old_image)

    return jsonify({"success": True, "profile_image": new_path})


@login_required_api
def delete_group_photo(conversation_id):
    """그룹 채팅 사진을 지우고 기본 이미지로 되돌린다(DELETE .../photo). 방장만 가능하다."""
    user_id = session["user_id"]

    with get_db() as conn:
        conv = conn.execute(
            "SELECT is_group, owner_id, profile_image, is_disabled FROM conversations WHERE id = %s",
            (conversation_id,),
        ).fetchone()
        if not conv or not conv["is_group"]:
            return (
                jsonify({"success": False, "error": "그룹 채팅만 사진을 삭제할 수 있습니다."}),
                400,
            )
        if conv["owner_id"] != user_id:
            return (
                jsonify({"success": False, "error": "방장만 그룹 사진을 삭제할 수 있습니다."}),
                403,
            )
        if conv["is_disabled"]:
            return (
                jsonify(
                    {"success": False, "error": "종료된 그룹 채팅방은 정보를 변경할 수 없습니다."}
                ),
                403,
            )

        old_image = conv["profile_image"]
        conn.execute(
            "UPDATE conversations SET profile_image = %s WHERE id = %s",
            (DEFAULT_PROFILE_IMAGE, conversation_id),
        )
        conn.commit()
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )

    if old_image and old_image != DEFAULT_PROFILE_IMAGE:
        delete_image_file(old_image)

    return jsonify({"success": True, "profile_image": DEFAULT_PROFILE_IMAGE})


# === 이메일 발송 ===
# Resend 서비스로 인증·재설정·아이디 안내 메일을 보낸다.
def email_copy(kind, language, code=None, username=None):
    """인증 관련 메일의 제목과 HTML 본문을 화면 언어에 맞게 돌려준다.

    Args:
        kind: 'verification'(가입 인증), 'reset'(비밀번호 재설정), 'username'(아이디 안내).
        language: 언어 코드. 지원하지 않는 언어는 한국어로 대체한다.
        code: 인증 코드.
        username: 아이디 안내 메일에 넣을 아이디.

    Returns:
        (제목, HTML 본문) 튜플. 인증 코드는 어느 언어에서든 굵게 눈에 띄게 둔다.
    """
    # 언어 → 메일 종류 → (제목, 본문) 사전. 새 언어를 추가하면 여기에 항목을 더한다.
    copies = {
        "en": {
            "verification": (
                "Email verification code",
                f"<p>Your verification code: <strong>{code}</strong></p><p>Enter it within 3 minutes.</p>",
            ),
            "reset": (
                "Cloud Chatting password reset code",
                f"<p>Use this code to reset your password.</p><p>Verification code: <strong>{code}</strong></p><p>Enter it within 3 minutes.</p>",
            ),
            "username": (
                "Cloud Chatting username reminder",
                f"<p>Here is the username you requested.</p><p>Username: <strong>{username}</strong></p>",
            ),
        },
        "zh": {
            "verification": (
                "邮箱验证码",
                f"<p>验证码：<strong>{code}</strong></p><p>请在 3 分钟内输入。</p>",
            ),
            "reset": (
                "Cloud Chatting 密码重置验证码",
                f"<p>这是密码重置验证码。</p><p>验证码：<strong>{code}</strong></p><p>请在 3 分钟内输入。</p>",
            ),
            "username": (
                "Cloud Chatting 用户名提醒",
                f"<p>这是您请求的用户名。</p><p>用户名：<strong>{username}</strong></p>",
            ),
        },
        "ja": {
            "verification": (
                "メール認証コード",
                f"<p>認証コード：<strong>{code}</strong></p><p>3分以内に入力してください。</p>",
            ),
            "reset": (
                "Cloud Chatting パスワード再設定コード",
                f"<p>パスワード再設定コードです。</p><p>認証コード：<strong>{code}</strong></p><p>3分以内に入力してください。</p>",
            ),
            "username": (
                "Cloud Chatting IDのお知らせ",
                f"<p>ご依頼のIDです。</p><p>ID：<strong>{username}</strong></p>",
            ),
        },
        "es": {
            "verification": (
                "Código de verificación de correo",
                f"<p>Tu código de verificación: <strong>{code}</strong></p><p>Introdúcelo en menos de 3 minutos.</p>",
            ),
            "reset": (
                "Código para restablecer la contraseña de Cloud Chatting",
                f"<p>Este es tu código para restablecer la contraseña.</p><p>Código: <strong>{code}</strong></p><p>Introdúcelo en menos de 3 minutos.</p>",
            ),
            "username": (
                "Recordatorio de usuario de Cloud Chatting",
                f"<p>Este es el usuario solicitado.</p><p>Usuario: <strong>{username}</strong></p>",
            ),
        },
        "ko": {
            "verification": (
                "이메일 인증 코드",
                f"<p>인증 코드: <strong>{code}</strong></p><p>3분 이내에 입력해주세요.</p>",
            ),
            "reset": (
                "클라우드 채팅 비밀번호 재설정 코드",
                f"<p>비밀번호 재설정 코드입니다.</p><p>인증 코드: <strong>{code}</strong></p><p>3분 이내에 입력해주세요.</p>",
            ),
            "username": (
                "클라우드 채팅 아이디 안내",
                f"<p>요청하신 아이디 안내입니다.</p><p>아이디: <strong>{username}</strong></p>",
            ),
        },
    }
    # 지원하지 않는 언어는 한국어로 대체한다.
    return copies.get(language, copies["ko"])[kind]


def send_verification_email(email, code):
    """회원가입 이메일 인증 코드를 메일로 보낸다. 언어는 현재 화면 언어를 따른다."""
    subject, html = email_copy("verification", get_interface_language(), code=code)
    resend.Emails.send(
        {
            "from": get_resend_sender(),
            "to": email,
            "subject": subject,
            "html": html,
        }
    )


def get_resend_sender():
    """메일 발신 주소(RESEND_FROM_EMAIL)를 돌려준다. 설정이 없으면 메일이 조용히 실패하지 않도록 오류를 낸다."""
    sender = os.environ.get("RESEND_FROM_EMAIL")
    if not sender:
        raise RuntimeError("RESEND_FROM_EMAIL 환경변수가 설정되지 않았습니다.")
    return sender


def send_password_reset_email(email, code):
    """비밀번호 재설정 코드를 메일로 보낸다. 언어는 현재 화면 언어를 따른다."""
    subject, html = email_copy("reset", get_interface_language(), code=code)
    resend.Emails.send(
        {
            "from": get_resend_sender(),
            "to": email,
            "subject": subject,
            "html": html,
        }
    )


# === 비밀번호 재설정 · 아이디 찾기 · 이메일 인증 ===
# 공통 원칙: 인증번호는 6자리 숫자, 유효시간 3분, IP별 요청 횟수 제한.
@app.route("/api/password-reset/send-code", methods=["POST"])
@rate_limit(5, 15 * 60, "password_reset_email")
def send_password_reset_code():
    """비밀번호 재설정 인증번호를 메일로 보낸다(POST /api/password-reset/send-code).

    가입 여부와 상관없이 같은 안내 문구를 돌려줘서, 이 API로 가입된 이메일을 알아낼 수 없게 한다.
    메일 발송이 실패한 경우에만 오류를 알려 준다.
    """
    email = (request.get_json() or {}).get("email", "").strip().lower()

    # 가입 여부와 상관없이 같은 문구를 쓴다(계정 존재 여부 노출 방지).
    message = "입력한 이메일로 가입된 계정이 있다면 인증 코드를 보냈습니다."

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": True, "message": message})

    with get_db() as conn:
        user = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()

        if not user:
            return jsonify({"success": True, "message": message})

        # 6자리 숫자 인증번호(앞자리 0 포함). 주의: random은 암호학적으로 안전한 난수가 아니다. 보안을 더 높이려면 secrets 모듈로 바꾸는 것이 좋다.
        code = f"{random.randint(0, 999999):06d}"
        kst = timezone(timedelta(hours=9))
        # 유효시간 3분. now_str()과 같은 형식(KST 문자열)이라 문자열 비교만으로 만료를 판단한다.
        expires_at = (datetime.now(kst) + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")

        # 같은 이메일의 이전 코드는 지우고 새 코드 하나만 둔다(이메일당 하나만 유효).
        conn.execute("DELETE FROM password_reset_codes WHERE email = %s", (email,))
        conn.execute(
            """
            INSERT INTO password_reset_codes
                (email, code, expires_at, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (email, code, expires_at, now_str()),
        )
        conn.commit()

    try:
        send_password_reset_email(email, code)
    except Exception:
        # 발송 실패를 성공처럼 응답하면 사용자가 원인을 알 수 없으므로, 이 경우에는 오류(503)로 알린다.
        app.logger.exception("비밀번호 재설정 메일 발송 실패")
        return (
            jsonify(
                {
                    "success": False,
                    "error": "인증번호 이메일 전송에 실패했습니다. 관리자에게 문의해주세요.",
                }
            ),
            503,
        )

    return jsonify({"success": True, "message": message})


@app.route("/api/password-reset/verify-code", methods=["POST"])
@rate_limit(12, 15 * 60, "password_reset_verify")
def verify_password_reset_code():
    """재설정 인증번호가 맞고 유효한지만 미리 확인한다(POST /api/password-reset/verify-code). 비밀번호는 바꾸지 않는다."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email) or not re.fullmatch(r"\d{6}", code):
        return jsonify({"success": False, "error": "이메일과 인증번호 6자리를 확인해주세요."}), 400

    with get_db() as conn:
        reset_code = conn.execute(
            "SELECT expires_at FROM password_reset_codes WHERE email = %s AND code = %s",
            (email, code),
        ).fetchone()

    if not reset_code:
        return jsonify({"success": False, "error": "인증번호가 올바르지 않습니다."}), 400
    # 만료 시각이 'YYYY-MM-DD HH:MM:SS' 문자열이라 문자열 비교로 시간 순서를 판단할 수 있다.
    if reset_code["expires_at"] < now_str():
        return (
            jsonify({"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."}),
            400,
        )
    return jsonify({"success": True, "message": "이메일 인증이 완료되었습니다."})


@app.route("/api/password-reset/confirm", methods=["POST"])
@rate_limit(8, 15 * 60, "password_reset_confirm")
def confirm_password_reset():
    """인증번호를 확인하고 새 비밀번호로 바꾼다(POST /api/password-reset/confirm).

    비밀번호를 바꾼 뒤에는 사용한 인증번호를 지워 다시 쓸 수 없게 한다.
    """
    data = request.get_json() or {}

    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    new_password = data.get("new_password") or ""
    password_confirmation = (
        data.get("password_confirmation") or data.get("new_password_confirmation") or ""
    )

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."}), 400

    if password_confirmation and new_password != password_confirmation:
        return jsonify({"success": False, "error": "비밀번호 확인이 일치하지 않습니다."}), 400

    if not PasswordPolicy.is_valid(new_password):
        return (
            jsonify(
                {
                    "success": False,
                    "error": PasswordPolicy.error_message(),
                }
            ),
            400,
        )

    with get_db() as conn:
        reset_code = conn.execute(
            """
            SELECT * FROM password_reset_codes
            WHERE email = %s AND code = %s
            """,
            (email, code),
        ).fetchone()

        if not reset_code:
            return jsonify({"success": False, "error": "인증번호가 올바르지 않습니다."}), 400

        if reset_code["expires_at"] < now_str():
            return (
                jsonify(
                    {"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."}
                ),
                400,
            )

        # 비밀번호를 재설정하면 토큰을 지워 모든 기기의 기존 로그인을 끊는다.
        conn.execute(
            "UPDATE users SET password_hash = %s, session_token = NULL WHERE email = %s",
            (generate_password_hash(new_password), email),
        )
        # 비밀번호를 바꾼 뒤에는 코드를 지워 재사용을 막는다.
        conn.execute("DELETE FROM password_reset_codes WHERE email = %s", (email,))
        conn.commit()

    return jsonify({"success": True})


def send_username_reminder_email(email, username):
    """가입 이메일로 아이디를 안내하는 메일을 보낸다."""
    subject, html = email_copy("username", get_interface_language(), username=username)
    resend.Emails.send(
        {
            "from": get_resend_sender(),
            "to": email,
            "subject": subject,
            "html": html,
        }
    )


@app.route("/api/find-username", methods=["POST"])
@rate_limit(5, 15 * 60, "find_username")
def find_username():
    """이메일로 아이디를 찾아 안내 메일을 보낸다(POST /api/find-username).

    가입 여부와 상관없이 같은 안내 문구를 돌려줘, 이메일이 가입돼 있는지 알아내는 데 쓸 수 없게 한다.
    """
    email = (request.get_json() or {}).get("email", "").strip().lower()

    # 이메일 형식이 틀리거나 가입되지 않았어도 같은 응답을 줘서 계정 존재 여부를 감춘다.
    message = "입력한 이메일로 가입된 계정이 있다면 아이디 안내 메일을 보냈습니다."

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": True, "message": message})

    with get_db() as conn:
        user = conn.execute("SELECT username FROM users WHERE email = %s", (email,)).fetchone()

    if user:
        try:
            send_username_reminder_email(email, user["username"])
        except Exception:
            app.logger.exception("아이디 안내 이메일 발송 실패")
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "아이디 안내 이메일 전송에 실패했습니다. 관리자에게 문의해주세요.",
                    }
                ),
                503,
            )

    return jsonify({"success": True, "message": message})


@app.route("/api/send-verification-code", methods=["POST"])
@rate_limit(5, 15 * 60, "registration_email")
def send_verification_code():
    """회원가입용 이메일 인증번호(6자리, 유효 3분)를 만들어 메일로 보낸다(POST /api/send-verification-code)."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."}), 400

    with get_db() as conn:
        # 이미 가입된 이메일에는 가입용 인증번호를 보내지 않는다.
        existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            return jsonify({"success": False, "error": "이미 가입된 이메일입니다."}), 400

        code = f"{random.randint(0, 999999):06d}"
        kst = timezone(timedelta(hours=9))
        expires_at = (datetime.now(kst) + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("DELETE FROM email_verification_codes WHERE email = %s", (email,))
        conn.execute(
            "INSERT INTO email_verification_codes (email, code, expires_at, created_at) VALUES (%s, %s, %s, %s)",
            (email, code, expires_at, now_str()),
        )
        conn.commit()

    try:
        send_verification_email(email, code)
    except Exception:
        app.logger.exception("이메일 발송 실패 (email=%s)", email)
        return (
            jsonify(
                {
                    "success": False,
                    "error": "이메일 전송에 실패했습니다. 잠시 후 다시 시도해주세요.",
                }
            ),
            500,
        )

    return jsonify({"success": True, "message": "인증 코드가 이메일로 전송되었습니다."})


@app.route("/api/verify-email-code", methods=["POST"])
@rate_limit(12, 15 * 60, "registration_verify")
def verify_email_code():
    """가입 전에 인증번호가 맞는지 미리 확인해 화면에 완료 상태를 보여 준다. 코드는 실제 가입 단계에서 한 번 더 검증하고 소모한다."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email) or not re.fullmatch(r"\d{6}", code):
        return jsonify({"success": False, "error": "이메일과 인증번호 6자리를 확인해주세요."}), 400

    with get_db() as conn:
        verification = conn.execute(
            "SELECT expires_at FROM email_verification_codes WHERE email = %s AND code = %s",
            (email, code),
        ).fetchone()
    if not verification:
        return jsonify({"success": False, "error": "인증번호가 올바르지 않습니다."}), 400
    if verification["expires_at"] < now_str():
        return (
            jsonify({"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."}),
            400,
        )
    return jsonify({"success": True, "message": "이메일 인증이 완료되었습니다."})


@app.route("/api/account/email/send-code", methods=["POST"])
@login_required_api
@rate_limit(5, 15 * 60, "account_email")
def send_account_email_code():
    """이메일을 바꾸려는 로그인 사용자에게, 새 이메일 주소로 인증번호를 보낸다. 다른 계정이 이미 쓰는 이메일은 거부한다."""
    user_id = session["user_id"]
    data = request.get_json() or {}
    # 이메일은 항상 소문자로 맞춰 저장·비교한다.
    new_email = (data.get("email") or "").strip().lower()

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", new_email):
        return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."}), 400

    with get_db() as conn:
        # 내 계정을 제외하고 이미 쓰이는 이메일인지 확인한다.
        existing = conn.execute(
            "SELECT id FROM users WHERE email = %s AND id != %s", (new_email, user_id)
        ).fetchone()
        if existing:
            return jsonify({"success": False, "error": "이미 사용 중인 이메일입니다."}), 400

        code = f"{random.randint(0, 999999):06d}"
        kst = timezone(timedelta(hours=9))
        expires_at = (datetime.now(kst) + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute("DELETE FROM email_verification_codes WHERE email = %s", (new_email,))
        conn.execute(
            "INSERT INTO email_verification_codes (email, code, expires_at, created_at) VALUES (%s, %s, %s, %s)",
            (new_email, code, expires_at, now_str()),
        )
        conn.commit()

    try:
        send_verification_email(new_email, code)
    except Exception:
        app.logger.exception("이메일 발송 실패 (email=%s)", new_email)
        return (
            jsonify(
                {
                    "success": False,
                    "error": "이메일 전송에 실패했습니다. 잠시 후 다시 시도해주세요.",
                }
            ),
            500,
        )

    return jsonify({"success": True, "message": "인증 코드가 이메일로 전송되었습니다."})


@app.route("/api/account/email", methods=["PATCH"])
@login_required_api
def update_account_email():
    """인증번호와 현재 비밀번호를 확인한 뒤 내 이메일을 바꾼다(PATCH /api/account/email).

    관리자 권한은 이메일로 정해지므로(ADMIN_EMAIL), 이메일이 바뀌면 관리자 여부도 다시 계산된다.
    """
    user_id = session["user_id"]
    data = request.get_json() or {}
    new_email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    current_password = data.get("current_password") or ""

    with get_db() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"success": False, "error": "현재 비밀번호가 일치하지 않습니다."})

        verification = conn.execute(
            "SELECT * FROM email_verification_codes WHERE email = %s AND code = %s",
            (new_email, code),
        ).fetchone()
        if not verification:
            return jsonify({"success": False, "error": "인증번호가 올바르지 않습니다."})
        if verification["expires_at"] < now_str():
            return jsonify(
                {"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."}
            )

        # 인증번호를 보낸 뒤 다른 사람이 그 이메일을 먼저 쓰게 됐을 수 있어 한 번 더 확인한다.
        existing = conn.execute(
            "SELECT id FROM users WHERE email = %s AND id != %s", (new_email, user_id)
        ).fetchone()
        if existing:
            return jsonify({"success": False, "error": "이미 사용 중인 이메일입니다."})

        conn.execute(
            "UPDATE users SET email = %s, is_admin = %s WHERE id = %s",
            # 이메일이 ADMIN_EMAIL과 같으면 관리자 권한을 주고, 다른 이메일로 바꾸면 회수한다.
            (new_email, bool(ADMIN_EMAIL and new_email == ADMIN_EMAIL), user_id),
        )
        conn.execute("DELETE FROM email_verification_codes WHERE email = %s", (new_email,))
        conn.commit()

    # 화면 렌더링에 쓰는 세션 값도 함께 바꾼다.
    session["email"] = new_email
    return jsonify({"success": True, "email": new_email})


@login_required_api
def read_conversation(conversation_id):
    """대화방을 열었을 때 내 읽음 위치를 최신 메시지로 옮긴다(POST .../read). 안 읽은 개수 표시가 이 값에 달려 있다."""
    user_id = session["user_id"]
    if not chat_service.mark_read(conversation_id, user_id):
        return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404
    return jsonify({"success": True})


# === Blueprint 등록과 서버 시작 ===
# 라우트 표(CHAT_ROUTES, ADMIN_ROUTES)에 적힌 이름의 함수를 이 모듈 전역에서 찾아 연결한다.
# 표에 이름을 추가했는데 함수가 없으면 시작할 때 KeyError가 난다.
chat_bp = create_chat_blueprint({endpoint: globals()[endpoint] for _, _, endpoint in CHAT_ROUTES})
app.register_blueprint(chat_bp)
admin_bp = create_admin_blueprint(
    {endpoint: globals()[endpoint] for _, _, endpoint in ADMIN_ROUTES}
)
app.register_blueprint(admin_bp)


try:
    # 서버가 시작될 때 필요한 테이블을 만든다. DB가 아직 준비되지 않았어도 서버는 뜨지만 이때는 테이블이 만들어지지 않는다. DB가 준비된 뒤 서버를 다시 시작해야 한다.
    init_db()
except Exception as e:
    app.logger.warning("초기 DB 생성 실패 (서버 연결 대기 중일 수 있음): %s", e)

# 정리 작업은 백그라운드 스레드로 계속 돈다(요청 제한 기록 정리, 만료된 인증코드 삭제).
socketio.start_background_task(cleanup_rate_limit_buckets)
socketio.start_background_task(cleanup_stale_db_rows)


if __name__ == "__main__":
    # 로컬 개발용 실행(python app.py). 운영에서는 Procfile의 gunicorn이 app:app을 직접 띄운다.
    socketio.run(app, debug=True)

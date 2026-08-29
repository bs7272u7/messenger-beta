# Cloud Chatting 서버의 중심 파일입니다.
# 기능을 추가할 때는 "입력 검증 → 권한 확인 → DB 저장 → 실시간 알림" 순서를 먼저 확인합니다.

from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for, abort
from flask_socketio import SocketIO, join_room
import json
import os
import base64
import uuid
import re
import random
import time
import secrets
import hmac
import io
import traceback
from threading import Lock
from collections import Counter, deque
import resend
import ipaddress
import socket
from html.parser import HTMLParser
from html import escape
from urllib.parse import urljoin, urlparse
import requests
import cloudinary
import cloudinary.uploader
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv
from extensions import init_extensions, login_manager
from models.user import User
from flask_login import current_user, login_user, logout_user
from repositories.user_repository import UserRepository
from services.auth_service import AuthService
from services.password_policy import PasswordPolicy
from services.registration_service import RegistrationService
from services.friend_service import FriendService
from services.chat_service import ChatService, ChatServiceError
from services.message_service import MessageService, MessageServiceError
from services.admin_service import AdminService, AdminServiceError
from blueprints.auth import create_auth_blueprint
from blueprints.profile import create_profile_blueprint
from blueprints.support import create_support_blueprint
from blueprints.friends import create_friends_blueprint
from blueprints.chat import CHAT_ROUTES, create_chat_blueprint
from blueprints.admin import ADMIN_ROUTES, create_admin_blueprint
import psycopg2
import psycopg2.extras
import psycopg2.pool
from chess_engine import ChessBoard, STARTING_FEN
from chess_engine.board import opponent
from config import AppConfig

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = Exception

try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None

load_dotenv()
resend.api_key = os.environ.get("RESEND_API_KEY")

app = Flask(__name__)
app_config = AppConfig.from_env(app.root_path)

# SENTRY_DSN이 설정된 경우에만 활성화된다. 초기화 자체가 실패해도(DSN 형식 오류 등)
# 서버 전체가 못 뜨는 일이 없도록 반드시 감싸서 실행한다.
if sentry_sdk and os.environ.get("SENTRY_DSN"):
    try:
        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"].strip().strip("\"'"), send_default_pii=True)
    except Exception as e:
        app.logger.warning("Sentry 초기화 실패, 에러 추적 없이 계속 진행합니다: %s", e)

app.config["MAX_CONTENT_LENGTH"] = app_config.max_content_length

if not os.environ.get("SECRET_KEY") and os.environ.get("RENDER_EXTERNAL_URL"):
    raise RuntimeError("운영 환경에서는 SECRET_KEY를 반드시 설정해야 합니다.")

app.secret_key = app_config.secret_key or "dev-secret-key-change-this-in-production"

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # 로컬 HTTP 개발은 유지하고, Render HTTPS에서는 보안 쿠키를 강제한다.
    SESSION_COOKIE_SECURE=app_config.session_cookie_secure,
    WTF_CSRF_CHECK_DEFAULT=False,
)

init_extensions(app)

# 별도 외부 도메인 연결은 허용하지 않고, 서비스와 같은 출처의 웹소켓만 받는다.
socketio = SocketIO(app, async_mode="threading")

# 여러 스레드가 동시에 emit을 호출할 때를 대비해 직렬화한다.
_emit_lock = Lock()


def emit_safe(*args, **kwargs):
    with _emit_lock:
        socketio.emit(*args, **kwargs)


# 이미지/동영상이 저장될 폴더와 기본 프로필 사진 경로
UPLOAD_DIR = app_config.upload_directory
SUPPORT_EMAIL = app_config.support_email
ADMIN_EMAIL = app_config.admin_email or ""

os.makedirs(UPLOAD_DIR, exist_ok=True)
DEFAULT_PROFILE_IMAGE = "/static/default_profile.png"
CLOUDINARY_ENABLED = all(
    os.environ.get(name)
    for name in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET")
)
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "bs7272u7/messenger-beta")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
UPDATE_HISTORY_CACHE_SECONDS = 600
_update_history_cache = {
    "recent": {"expires_at": 0, "data": None},
    "all": {"expires_at": 0, "data": None},
}
ADMIN_ACCESS_KEY_HASH = os.environ.get("ADMIN_ACCESS_KEY_HASH")
ADMIN_ACCESS_SESSION_SECONDS = 30 * 60
ADMIN_ACCESS_MAX_FAILURES = 5
ADMIN_ACCESS_LOCK_SECONDS = 15 * 60
SUPPORTED_LANGUAGES = {"ko", "en", "zh", "ja", "es"}
SUPPORT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
SUPPORT_ATTACHMENT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "webm", "mov"}
SUPPORT_INQUIRY_MAX_PER_USER = 1
REVIEW_MAX_PER_USER = 1
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
# 체스 기능은 보존하되, 정식 채팅 화면에서는 기본적으로 노출하지 않는다.
# 다시 공개할 때만 CHESS_UI_ENABLED=true로 설정한다.
CHESS_UI_ENABLED = os.environ.get("CHESS_UI_ENABLED", "false").strip().lower() == "true"
IMAGE_MAX_BYTES = 10 * 1024 * 1024
IMAGE_MAX_PIXELS = 40_000_000
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL")
active_socket_ids = {}
active_socket_ids_lock = Lock()
_rate_limit_buckets = {}
_rate_limit_lock = Lock()
_recent_errors = deque(maxlen=50)
_recent_errors_lock = Lock()

if CLOUDINARY_ENABLED:
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


def get_csrf_token():
    """세션마다 예측 불가능한 토큰을 발급해 외부 사이트의 요청 위조를 막는다."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def get_interface_language():
    """로그인 전 인증 화면도 같은 언어를 쓸 수 있도록 요청 헤더를 우선 확인한다."""
    language = request.headers.get("X-App-Language") or session.get("language") or "ko"
    return language if language in SUPPORTED_LANGUAGES else "ko"


@app.context_processor
def inject_security_values():
    return {"csrf_token": get_csrf_token()}


@app.before_request
def protect_from_csrf():
    """브라우저 세션을 사용하는 모든 상태 변경 API는 CSRF 헤더를 요구한다."""
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


@app.after_request
def add_security_headers(response):
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


# API 라우트는 실패해도 항상 JSON을 반환해야 프런트가 response.json()을 안전하게 쓸 수 있다.
# 기본 Flask 에러 페이지는 HTML이라 "<!doctype..."을 JSON으로 파싱하려다 깨지는 문제가 있었다.
@app.errorhandler(404)
def handle_api_404(error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "요청한 항목을 찾을 수 없습니다."}), 404
    return error


@app.errorhandler(405)
def handle_api_405(error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "허용되지 않은 요청 방식입니다."}), 405
    return error


@app.errorhandler(500)
def handle_api_500(error):
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
    # Render 프록시 뒤에서는 X-Forwarded-For의 첫 주소가 실제 접속자 IP다.
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",", 1)[0].strip() if forwarded else (request.remote_addr or "unknown")


def get_authenticated_user_id() -> int | None:
    """새 Flask-Login 세션과 기존 세션을 모두 지원한다."""
    if current_user.is_authenticated:
        return int(current_user.id)

    legacy_user_id = session.get("user_id")
    return int(legacy_user_id) if legacy_user_id is not None else None


def rate_limit(limit, window_seconds, scope):
    """로그인·인증 메일 API의 자동화 남용을 줄이는 가벼운 IP 단위 제한이다."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            now = time.time()
            key = (scope, get_client_ip())
            with _rate_limit_lock:
                attempts = [
                    stamp
                    for stamp in _rate_limit_buckets.get(key, [])
                    if stamp > now - window_seconds
                ]
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


_RATE_LIMIT_RETENTION_SECONDS = 60 * 60  # 가장 긴 rate_limit 윈도우(1시간)와 맞춘 보존 기간


def cleanup_rate_limit_buckets():
    """오래전에 요청이 끊긴 IP 항목을 주기적으로 지워 메모리가 무한정 늘어나지 않게 한다."""
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
    """아무도 들어오지 않은 대기 중 체스방, 만료된 인증 코드, 오래된 초대 기록을 주기적으로 정리한다."""
    while True:
        socketio.sleep(6 * 60 * 60)
        if not db_pool:
            continue
        try:
            with get_db() as conn:
                now = now_str()

                # 48시간 넘게 상대가 들어오지 않은 대기 중 체스방은 방치된 것으로 보고 정리한다.
                # (일부 초기 배포 DB에는 CASCADE 제약이 없을 수 있어 자식 테이블부터 명시적으로 지운다.)
                waiting_cutoff = (datetime.now(KST) - timedelta(hours=48)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                stale_games = conn.execute(
                    "SELECT id FROM chess_games WHERE status = 'waiting' AND created_at < %s",
                    (waiting_cutoff,),
                ).fetchall()
                stale_game_ids = [row["id"] for row in stale_games]
                if stale_game_ids:
                    conn.execute(
                        "DELETE FROM chess_game_moves WHERE game_id = ANY(%s::uuid[])",
                        (stale_game_ids,),
                    )
                    conn.execute(
                        "DELETE FROM chess_game_chat_messages WHERE game_id = ANY(%s::uuid[])",
                        (stale_game_ids,),
                    )
                    conn.execute(
                        "DELETE FROM chess_invites WHERE game_id = ANY(%s::uuid[])",
                        (stale_game_ids,),
                    )
                    conn.execute(
                        "DELETE FROM chess_games WHERE id = ANY(%s::uuid[])", (stale_game_ids,)
                    )

                # 만료된 인증/재설정 코드는 재요청 전까지 쓸모가 없으니 바로 지운다.
                conn.execute("DELETE FROM email_verification_codes WHERE expires_at < %s", (now,))
                conn.execute("DELETE FROM password_reset_codes WHERE expires_at < %s", (now,))

                # 처리 완료된(대기 중이 아닌) 체스 초대는 7일 지나면 기록만 남기지 않고 정리한다.
                invite_cutoff = (datetime.now(KST) - timedelta(days=7)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                conn.execute(
                    "DELETE FROM chess_invites WHERE status != 'pending' AND created_at < %s",
                    (invite_cutoff,),
                )

                conn.commit()
        except Exception as e:
            app.logger.warning("정기 데이터 정리 실패: %s", e)


class OpenGraphParser(HTMLParser):
    """Extract a small, safe subset of Open Graph metadata from a page."""

    def __init__(self):
        super().__init__()
        self.metadata = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
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
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def is_public_web_url(url):
    """Reject local/private addresses so the preview endpoint cannot be used for SSRF."""
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
        return all(ipaddress.ip_address(address[4][0]).is_global for address in addresses)
    except (socket.gaierror, ValueError):
        return False


def get_link_preview(url):
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
        for _ in range(4):
            if not is_public_web_url(current_url):
                return None
            response = requests.get(
                current_url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Messenger-Beta-LinkPreview/1.0)"},
                timeout=5,
                stream=True,
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
    """GitHub 커밋을 사용자에게 보여줄 업데이트 내역으로 변환한다.

    재현님이 한국어 커밋 메시지를 작성하면 그 문장이 그대로 사용자 화면에 표시된다.
    기본 목록은 최근 10개, 이전 업데이트 목록은 전체 기록을 보여준다.
    GitHub API를 매번 호출하지 않도록 각각 10분 동안 메모리에 보관한다.
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
        # 전체 목록도 한 번에 과도한 호출을 하지 않도록 최대 1,000개까지만 순회한다.
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


# PostgreSQL 접속 정보 정규화
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME", "messenger-beta")
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require" if DATABASE_URL else "prefer")


# ----------------------------------------------------------------
# Database Connection Pool 초기화
# ----------------------------------------------------------------
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
    db_pool = None


class PGConn:
    """psycopg2용 커넥션 Wrapper 어댑터 (순수 PostgreSQL 호환)"""

    def __init__(self, raw_conn, pool_obj=None):
        self.raw_conn = raw_conn
        self.pool_obj = pool_obj
        self._cursor = raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def cursor(self):
        return self.raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, query, params=()):
        self._cursor.execute(query, params)
        return self

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def commit(self):
        self.raw_conn.commit()

    def close(self, discard=False):
        try:
            self._cursor.close()
        except Exception:
            pass
        # 커넥션을 닫지 않고 풀(Pool)에 반납합니다. 단, 손상된 커넥션(discard=True)은
        # 풀에 되돌리지 않고 폐기합니다 - 그대로 반납하면 다음 요청이 같은 SSL 오류를 다시 겪습니다.
        if self.pool_obj:
            self.pool_obj.putconn(self.raw_conn, close=discard)
        else:
            self.raw_conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
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
    if db_pool:
        raw_conn = db_pool.getconn()
        raw_conn.autocommit = False
        return PGConn(raw_conn, pool_obj=db_pool)
    else:
        # 풀 초기화 실패 시 폴백 (단일 커넥션)
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
admin_service = AdminService()


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Flask-Login이 세션의 사용자 ID로 현재 사용자를 복원할 때 사용한다."""
    if not user_id.isdigit():
        return None

    conn = get_db()
    try:
        row = conn.execute(
            """
        SELECT id, username, display_name, email, is_admin,
                   profile_visibility, is_suspended, suspended_until,
                   language, chess_rating, chess_wins, chess_draws,
                   chess_losses, created_at
            FROM users
            WHERE id = %s

        """,
            (int(user_id),),
        ).fetchone()

        return User.from_row(row) if row else None
    finally:
        conn.close()


# ----------------------------------------------------------------
# 헬퍼 함수
# ----------------------------------------------------------------


def get_membership(conn, conversation_id, user_id):
    return conn.execute(
        "SELECT * FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
        (conversation_id, user_id),
    ).fetchone()


def get_owned_message(conn, user_id, message_id):
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
    # Render 서버 환경을 대비해 한국 시간(KST, UTC+9)으로 고정
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")


KST = timezone(timedelta(hours=9))


def current_message_timestamp_ms():
    """메시지의 기준 시각은 UTC epoch 밀리초로 저장해 모든 국가에서 같은 순간을 가리킨다."""
    return int(time.time() * 1000)


def legacy_message_labels(sent_at_ms):
    """기존 time/date 컬럼 호환용 표기는 한국 시간으로만 유지하고, 화면 표시는 브라우저가 맡는다."""
    moment = datetime.fromtimestamp(sent_at_ms / 1000, timezone.utc).astimezone(KST)
    hour = moment.hour % 12 or 12
    return (
        f"{'오후' if moment.hour >= 12 else '오전'} {hour}:{moment.minute:02d}",
        moment.strftime("%Y-%m-%d"),
    )


def legacy_message_timestamp_ms(date_text, time_text):
    """기존 한국 시간 문자열을 UTC 시각으로 옮긴다. 해석할 수 없는 오래된 값은 그대로 둔다."""
    if not date_text:
        return None
    try:
        date_value = datetime.strptime(str(date_text).replace(".", "-")[:10], "%Y-%m-%d").date()
        time_match = re.search(r"(오전|오후)\s*(\d{1,2}):(\d{2})", str(time_text or ""))
        if time_match:
            period, hour_text, minute_text = time_match.groups()
            hour, minute = int(hour_text), int(minute_text)
            if hour == 12:
                hour = 0
            if period == "오후":
                hour += 12
        else:
            plain_time = re.search(r"(\d{1,2}):(\d{2})", str(time_text or ""))
            hour, minute = (
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
    """서비스 전 메시지는 한국 시간으로 작성됐으므로 최초 실행 때만 안전하게 타임스탬프를 채운다."""
    rows = conn.execute("SELECT id, date, time FROM messages WHERE sent_at IS NULL").fetchall()
    for row in rows:
        sent_at = legacy_message_timestamp_ms(row["date"], row["time"])
        if sent_at is not None:
            conn.execute("UPDATE messages SET sent_at = %s WHERE id = %s", (sent_at, row["id"]))


def get_peer_id(conn, conversation_id, user_id):
    conv = conn.execute(
        "SELECT is_group FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    if not conv or conv["is_group"]:
        return None
    row = conn.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = %s AND user_id != %s",
        (conversation_id, user_id),
    ).fetchone()
    return row["user_id"] if row else None


def is_blocked_either_way(conn, user_a, user_b):
    row = conn.execute(
        "SELECT 1 FROM blocks WHERE (blocker_id = %s AND blocked_id = %s) OR (blocker_id = %s AND blocked_id = %s)",
        (user_a, user_b, user_b, user_a),
    ).fetchone()
    return row is not None


@socketio.on("connect")
def handle_socket_connect():
    if "user_id" not in session:
        return False
    user_id = session["user_id"]
    if is_user_suspended(user_id):
        return False
    with active_socket_ids_lock:
        active_socket_ids.setdefault(user_id, set()).add(request.sid)
    join_room(f"user_{user_id}")
    emit_safe("presence_updated", {"userId": user_id, "online": True})


@socketio.on("disconnect")
def handle_socket_disconnect():
    user_id = session.get("user_id")
    if not user_id:
        return
    with active_socket_ids_lock:
        socket_ids = active_socket_ids.get(user_id, set())
        socket_ids.discard(request.sid)
        if socket_ids:
            return
        active_socket_ids.pop(user_id, None)
    emit_safe("presence_updated", {"userId": user_id, "online": False})
    mark_chess_disconnect(user_id)


def is_user_online(user_id):
    # 한 사용자가 여러 탭을 열어도 마지막 탭까지 닫혀야 오프라인으로 바뀐다.
    with active_socket_ids_lock:
        return bool(active_socket_ids.get(user_id))


def get_conversation_member_ids(conn, conversation_id):
    rows = conn.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = %s", (conversation_id,)
    ).fetchall()
    return [row["user_id"] for row in rows]


def broadcast_to_conversation(conn, conversation_id, event, payload):
    # 메시지 수정·삭제처럼 대화방 전체가 알아야 하는 일은 참여자별 Socket.IO 방으로 보낸다.
    for uid in get_conversation_member_ids(conn, conversation_id):
        emit_safe(event, payload, room=f"user_{uid}")


def unhide_conversation(conn, conversation_id):
    conn.execute(
        "UPDATE conversation_members SET hidden_at = NULL WHERE conversation_id = %s",
        (conversation_id,),
    )


def notify_user(user_id, event, payload):
    emit_safe(event, payload, room=f"user_{user_id}")


def send_push_notification(conn, user_id, title, body, url="/"):
    """브라우저가 닫혀 있어도 도착하도록 Web Push 구독자에게 알림을 보낸다."""
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
            # 더 이상 유효하지 않은 브라우저 구독은 다음 전송부터 제외한다.
            if getattr(exc, "response", None) and exc.response.status_code in {404, 410}:
                conn.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = %s",
                    (subscription["endpoint"],),
                )
            else:
                app.logger.warning("푸시 알림 전송 실패: %s", exc)


def notify_conversation_message(conn, conversation_id, sender_id, preview):
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
    """확장자 위장·과도한 이미지 용량·압축 폭탄을 저장 전에 차단한다."""
    match = re.fullmatch(r"data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)", data_url or "")
    if not match or len(match.group(2)) > (IMAGE_MAX_BYTES * 4 // 3) + 4:
        return None, None
    try:
        raw_image = base64.b64decode(match.group(2), validate=True)
        if not raw_image or len(raw_image) > IMAGE_MAX_BYTES:
            return None, None
        Image.MAX_IMAGE_PIXELS = IMAGE_MAX_PIXELS
        with Image.open(io.BytesIO(raw_image)) as image:
            if image.width * image.height > IMAGE_MAX_PIXELS:
                return None, None
            image.verify()
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError, OSError):
        return None, None
    return raw_image, ("jpg" if match.group(1) == "jpeg" else match.group(1))


def save_base64_image(data_url):
    raw_image, ext = validate_base64_image(data_url)
    if raw_image is None:
        return None
    # Render의 임시 디스크 문제를 피하기 위해 Cloudinary가 설정되면 우선 사용한다.
    # 로컬 개발 중에는 기존 static/uploads 저장 방식으로 자동 폴백된다.
    try:
        if CLOUDINARY_ENABLED:
            result = cloudinary.uploader.upload(
                data_url,
                folder="messenger_beta/images",
                resource_type="image",
            )
            return result["secure_url"]

        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(raw_image)

        return f"/static/uploads/{filename}"
    except Exception as e:
        app.logger.error("이미지 디코딩 실패: %s", e)
        return None


def delete_image_file(image_path):
    if not image_path:
        return
    if CLOUDINARY_ENABLED and "/messenger_beta/images/" in image_path:
        try:
            path = urlparse(image_path).path.split("/upload/", 1)[1]
            path = re.sub(r"^v\d+/", "", path)
            cloudinary.uploader.destroy(os.path.splitext(path)[0], resource_type="image")
        except (IndexError, ValueError, KeyError):
            app.logger.warning("Cloudinary 이미지 삭제에 실패했습니다: %s", image_path)
        return
    if not image_path.startswith("/static/uploads/"):
        return
    filepath = os.path.join(app.root_path, image_path.lstrip("/"))
    if os.path.exists(filepath):
        os.remove(filepath)


def save_uploaded_file(upload, folder="files"):
    """채팅/문의 첨부 파일을 Cloudinary 또는 로컬 개발 폴더에 안전하게 저장한다."""
    original_name = os.path.basename(upload.filename or "file")
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

        stored_name = f"{uuid.uuid4().hex}{extension}"
        upload.save(os.path.join(UPLOAD_DIR, stored_name))
        return f"/static/uploads/{stored_name}", safe_name
    except Exception:
        app.logger.exception("첨부 파일 저장 실패")
        return None, None


def init_db():
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

        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)")
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE"
        )
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
        # 기기마다 언어가 달라지지 않도록 사용자 계정에 선택 언어를 함께 저장한다.
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS language VARCHAR(5) NOT NULL DEFAULT 'ko'"
        )
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS chess_rating INT NOT NULL DEFAULT 400"
        )
        cur.execute("ALTER TABLE users ALTER COLUMN chess_rating SET DEFAULT 400")
        # 승/무/패는 게임 행을 세어 계산하지 않고 레이팅처럼 계정에 직접 누적한다.
        # 그래야 전적(기보) 삭제 후에도 프로필의 승/무/패 숫자가 그대로 남는다.
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'chess_wins'"
        )
        chess_stats_columns_existed = cur.fetchone() is not None
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS chess_wins INT NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS chess_draws INT NOT NULL DEFAULT 0")
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS chess_losses INT NOT NULL DEFAULT 0"
        )
        # 기존 가입자는 가입 시점을 소급할 수 없어 NULL로 남는다 — 관리자 목록에서 "가입일 없음"으로 표시한다.
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
        cur.execute("ALTER TABLE moderation_actions ADD COLUMN IF NOT EXISTS seen_at TEXT")

        # 체스는 메신저 DB 연결 방식을 그대로 재사용해 배포 환경에서 ORM 이중화를 만들지 않는다.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chess_games (
                id UUID PRIMARY KEY,
                room_code VARCHAR(8) UNIQUE NOT NULL,
                white_player_id INT REFERENCES users(id) ON DELETE SET NULL,
                black_player_id INT REFERENCES users(id) ON DELETE SET NULL,
                mode VARCHAR(12) NOT NULL,
                ai_difficulty VARCHAR(12),
                fen TEXT NOT NULL,
                result TEXT,
                status VARCHAR(16) NOT NULL DEFAULT 'waiting',
                time_control VARCHAR(12) NOT NULL DEFAULT 'unlimited',
                white_remaining_ms BIGINT,
                black_remaining_ms BIGINT,
                turn_started_ms BIGINT,
                draw_offer_user_id INT REFERENCES users(id) ON DELETE SET NULL,
                disconnected_user_id INT REFERENCES users(id) ON DELETE SET NULL,
                disconnect_deadline_ms BIGINT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chess_game_moves (
                id SERIAL PRIMARY KEY,
                game_id UUID NOT NULL REFERENCES chess_games(id) ON DELETE CASCADE,
                move_number INT NOT NULL,
                san VARCHAR(32) NOT NULL,
                fen TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chess_games_room ON chess_games(room_code)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chess_moves_game ON chess_game_moves(game_id, move_number)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chess_invites (
                id SERIAL PRIMARY KEY,
                game_id UUID NOT NULL REFERENCES chess_games(id) ON DELETE CASCADE,
                inviter_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                invitee_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status VARCHAR(16) NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                UNIQUE (game_id, invitee_id)
            )
        """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chess_invites_invitee ON chess_invites(invitee_id, status)"
        )
        cur.execute(
            "ALTER TABLE chess_games ADD COLUMN IF NOT EXISTS ratings_applied BOOLEAN NOT NULL DEFAULT FALSE"
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS chess_game_chat_messages (
            id SERIAL PRIMARY KEY, game_id UUID NOT NULL REFERENCES chess_games(id) ON DELETE CASCADE,
            sender_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE, text VARCHAR(200) NOT NULL, created_at TEXT NOT NULL
        )"""
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_chess_game_chat ON chess_game_chat_messages(game_id, id)"
        )

        # ADMIN_EMAIL과 일치하는 계정만 관리자 권한을 부여한다.
        # 권한은 화면이나 세션이 아닌 DB에서 다시 확인하므로 주소를 직접 입력해도 우회할 수 없다.
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
        # 메시지 신고뿐 아니라 프로필에서 "사용자 자체"를 신고할 수 있도록 message_id를 선택 항목으로 바꾼다.
        cur.execute("ALTER TABLE reports ALTER COLUMN message_id DROP NOT NULL")
        cur.execute(
            "ALTER TABLE reports ADD COLUMN IF NOT EXISTS reported_user_id INT REFERENCES users(id) ON DELETE CASCADE"
        )
        # 같은 사람을 중복 신고하지 못하게 막되, 메시지 신고용 UNIQUE(reporter_id, message_id)와는 별개로 관리한다.
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

        # 기존 메시지는 당시 한국 시간 문자열을 UTC 기준 원본 시각으로 한 번만 변환한다.
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

        if not chess_stats_columns_existed:
            # 승/무/패 컬럼을 새로 추가하는 시점에만, 현재 남아있는 완료된 게임을 기준으로 초기값을 채운다.
            # (이후에는 게임 결과가 반영되는 시점에만 누적되고, 기보 삭제로는 줄어들지 않는다.)
            cur.execute(
                """
                SELECT result, white_player_id, black_player_id FROM chess_games
                WHERE status = 'finished' AND mode = 'online'
            """
            )
            player_stats = {}
            for game in cur.fetchall():
                result = json.loads(game["result"] or "{}")
                winner = result.get("winner")
                for player_id, color in (
                    (game["white_player_id"], "w"),
                    (game["black_player_id"], "b"),
                ):
                    if not player_id:
                        continue
                    stats = player_stats.setdefault(player_id, {"wins": 0, "draws": 0, "losses": 0})
                    if winner is None:
                        stats["draws"] += 1
                    elif winner == color:
                        stats["wins"] += 1
                    else:
                        stats["losses"] += 1
            for player_id, stats in player_stats.items():
                cur.execute(
                    "UPDATE users SET chess_wins = %s, chess_draws = %s, chess_losses = %s WHERE id = %s",
                    (stats["wins"], stats["draws"], stats["losses"], player_id),
                )

        conn.commit()
    except Exception:
        conn.raw_conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ----------------------------------------------------------------
# 로그인 보호용 데코레이터
# ----------------------------------------------------------------


def login_required_page(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
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
    @wraps(view)
    def wrapped(*args, **kwargs):
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
    """현재 로그인 계정의 관리자 권한을 DB에서 확인한다."""
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
    """영구·기간 정지를 하나의 상태로 판단하고, 끝난 기간 정지는 자동 해제한다."""
    if not user or not user["is_suspended"]:
        return None
    if user["suspended_until"] and user["suspended_until"] <= time.time():
        return "expired"
    return "permanent" if not user["suspended_until"] else "temporary"


def is_user_suspended(user_id):
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


auth_bp = create_auth_blueprint(
    auth_service=auth_service,
    registration_service=registration_service,
    connection_factory=get_db,
    user_loader=load_user,
    suspension_state_getter=get_suspension_state,
    supported_languages=SUPPORTED_LANGUAGES,
    login_rate_limit=rate_limit(10, 15 * 60, "login"),
    client_ip_getter=get_client_ip,
    api_login_required=login_required_api,
    register_rate_limit=rate_limit(5, 60 * 60, "register"),
    register_user_loader=load_user,
)
app.register_blueprint(auth_bp)


def are_users_friends(conn, user_a, user_b):
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
    """친구 요청 수락과 1:1 대화방 생성을 한 곳에서 처리한다."""
    friend_request = conn.execute(
        "SELECT * FROM friend_requests WHERE id = %s", (request_id,)
    ).fetchone()
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
    if not target or target["is_suspended"]:
        return False
    if viewer_id == target["id"] or target["profile_visibility"] == "public":
        return True
    return target["profile_visibility"] == "friends" and are_users_friends(
        conn, viewer_id, target["id"]
    )


def is_admin_access_verified():
    verified_until = session.get("admin_verified_until", 0)
    if verified_until and float(verified_until) > time.time():
        return True
    session.pop("admin_verified_until", None)
    return False


def admin_account_required_page(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_current_user_admin():
            abort(404)
        if is_user_suspended(session["user_id"]):
            session.clear()
            return redirect(url_for("login_page", suspended="1"))
        return view(*args, **kwargs)

    return wrapped


def admin_account_required_api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_current_user_admin():
            return jsonify({"success": False, "error": "관리자 권한이 필요합니다."}), 404
        if is_user_suspended(session["user_id"]):
            session.clear()
            return jsonify({"success": False, "error": "이용 정지 상태입니다."}), 403
        return view(*args, **kwargs)

    return wrapped


def admin_required_page(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # 관리자 페이지 존재 자체를 일반 사용자에게 노출하지 않는다.
        if not is_current_user_admin():
            abort(404)
        if not is_admin_access_verified():
            return redirect(url_for("admin.admin_access_verify"))
        return view(*args, **kwargs)

    return wrapped


def admin_required_api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_current_user_admin():
            return jsonify({"success": False, "error": "관리자 권한이 필요합니다."}), 404
        if not is_admin_access_verified():
            return jsonify({"success": False, "error": "관리자 접근 키를 다시 확인해주세요."}), 403
        return view(*args, **kwargs)

    return wrapped


# ----------------------------------------------------------------
# 페이지 라우트
# ----------------------------------------------------------------


@app.get("/healthz")
def health_check():
    """로드밸런서와 배포 환경이 앱·DB 상태를 확인하는 공개 헬스 체크."""
    try:
        with get_db() as conn:
            conn.execute("SELECT 1")
            conn.fetchone()
    except Exception as error:
        # 로드밸런서는 주기적으로 호출하므로 연결 실패의 전체 스택은 반복 기록하지 않는다.
        app.logger.warning("헬스 체크 DB 연결 실패: %s", error)
        return jsonify({"status": "degraded", "database": "unavailable"}), 503
    return jsonify({"status": "ok", "database": "available"})


@app.route("/")
def landing_page():
    """비로그인 사용자에게 Cloud Chatting 소개 화면을 제공한다."""
    if session.get("user_id"):
        return redirect(url_for("home"))
    return render_template("landing.html")


@app.route("/chat")
@login_required_page
def home():
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
    session["language"] = user["language"] if user["language"] in SUPPORTED_LANGUAGES else "ko"

    return render_template(
        "index.html",
        user_id=user_id,
        username=display_name,
        profile_image=profile_image,
        user_email=user["email"],
        user_language=session["language"],
        chess_ui_enabled=CHESS_UI_ENABLED,
    )


def conversation_is_disabled(conn, conversation_id):
    row = conn.execute(
        "SELECT is_disabled FROM conversations WHERE id = %s", (conversation_id,)
    ).fetchone()
    return bool(row and row["is_disabled"])


def create_system_message(conn, conversation_id, text, actor_id=None):
    """그룹 공지·테마 변경처럼 누구의 일반 메시지도 아닌 기록을 남긴다."""
    # Render 서버는 UTC로 동작할 수 있으므로, 시스템 메시지도 항상 한국 시간으로 기록한다.
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
    if row:
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (row["id"], conversation_id),
        )
    return row["id"] if row else None


def profile_update_recipient_ids(conn, user_id):
    """커밋 뒤에 프로필 갱신을 알릴 대화 상대의 ID를 모은다."""
    rows = conn.execute(
        """SELECT DISTINCT members.user_id
           FROM conversation_members mine
           JOIN conversation_members members ON members.conversation_id = mine.conversation_id
           WHERE mine.user_id = %s""",
        (user_id,),
    ).fetchall()
    return [row["user_id"] for row in rows]


def notify_profile_updated(recipient_ids, user_id):
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


@admin_required_page
def admin_page():
    """관리자만 접근할 수 있는 운영 페이지의 시작 화면."""
    return render_template("admin.html")


@admin_account_required_page
def admin_access_verify():
    if is_admin_access_verified():
        return redirect(url_for("admin.admin_page"))
    return render_template("admin_verify.html", access_key_configured=bool(ADMIN_ACCESS_KEY_HASH))


@admin_account_required_api
@rate_limit(8, 15 * 60, "admin_access")
def verify_admin_access_key():
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

        if check_password_hash(ADMIN_ACCESS_KEY_HASH, access_key):
            conn.execute("DELETE FROM admin_access_attempts WHERE user_id = %s", (user_id,))
            conn.commit()
            session["admin_verified_until"] = now + ADMIN_ACCESS_SESSION_SECONDS
            return jsonify({"success": True, "expires_in": ADMIN_ACCESS_SESSION_SECONDS})

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
    return render_template("legal.html", document_type="terms")


@app.route("/privacy")
def privacy_page():
    return render_template("legal.html", document_type="privacy")


@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("home"))
    initial_mode = "register" if request.args.get("mode") == "register" else "login"
    return render_template("login.html", initial_mode=initial_mode)


@app.route("/api/push-config", methods=["GET"])
@login_required_api
def push_config():
    return jsonify(
        {"enabled": bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY), "publicKey": VAPID_PUBLIC_KEY}
    )


@app.route("/api/push-subscriptions", methods=["POST", "DELETE"])
@login_required_api
def push_subscriptions():
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
    """경고는 다음 로그인 때 한 번 확인시키고, 확인 전 기록만 전달한다."""
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
    update_history = get_update_history(include_all=request.args.get("all") == "1")
    if update_history is None:
        return jsonify({"success": False, "error": "업데이트 내역을 불러오지 못했습니다."}), 503
    return jsonify({"success": True, **update_history})


@app.route("/api/notices", methods=["GET"])
@login_required_api
def get_notices():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, content, created_at FROM notices WHERE is_published = TRUE ORDER BY id DESC LIMIT 30"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@app.route("/api/reviews", methods=["GET", "POST"])
@login_required_api
def reviews():
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
        or rating not in range(1, 6)
        or len(content) < 5
        or len(content) > 1000
    ):
        return (
            jsonify({"success": False, "error": "별점(1~5점)과 5자 이상 후기를 입력해주세요."}),
            400,
        )
    with get_db() as conn:
        # 같은 계정의 동시 요청도 사용자 행 잠금으로 직렬화해 중복 작성을 우회하지 못하게 한다.
        conn.execute(
            "SELECT id FROM users WHERE id = %s FOR UPDATE", (session["user_id"],)
        ).fetchone()
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
    """본인이 작성한 리뷰만 수정하거나 삭제할 수 있다."""
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


@admin_required_api
def admin_recent_errors():
    """서버 재시작 전까지 최근 500 에러 최대 50건을 메모리에 보관해 관리자 페이지에서 바로 확인할 수 있게 한다."""
    with _recent_errors_lock:
        return jsonify(list(_recent_errors))


@admin_required_api
def admin_online_users():
    """지금 소켓으로 연결되어 있는(=실시간으로 접속 중인) 사용자 수와 목록을 보여준다."""
    with active_socket_ids_lock:
        user_ids = list(active_socket_ids.keys())
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
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, u.display_name, u.username FROM reviews r JOIN users u ON u.id = r.user_id ORDER BY r.id DESC
        """
        ).fetchall()
    return jsonify([dict(row) for row in rows])


@admin_required_api
def admin_review_detail(review_id):
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
    """체크된 리뷰만 삭제하며 빈 목록은 전체 삭제로 해석하지 않는다."""
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
    with get_db() as conn:
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
    """문의 한 건을 삭제한다. 첨부 파일 원본은 안전을 위해 자동 삭제하지 않는다."""
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
    """체크된 문의만 삭제하며 빈 목록은 전체 삭제로 해석하지 않는다."""
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
    """가입한 전체 사용자 목록을 아이디/이메일/가입일/정지 상태와 함께 페이지 단위로 보여준다."""
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page_size = min(100, max(1, request.args.get("page_size", 50, type=int) or 50))
    search = (request.args.get("search") or "").strip()
    offset = (page - 1) * page_size

    with get_db() as conn:
        # 만료된 기간 정지는 목록을 보여주기 전에 먼저 자동 해제한다(로그인 시 판정과 동일한 규칙).
        conn.execute(
            """UPDATE users
               SET is_suspended = FALSE, suspended_until = 0, suspension_reason = NULL
               WHERE is_suspended = TRUE AND suspended_until > 0 AND suspended_until <= %s""",
            (time.time(),),
        )
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
    """신고 목록과 관계없이 현재 이용 제한 중인 계정을 관리자가 해제할 수 있게 제공한다."""
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
    """신고 검토 후 경고·기간 정지·영구 정지·해제를 서버 권한으로 처리한다."""
    data = request.get_json() or {}
    try:
        action, report_id, reason = admin_service.moderation_request(
            data.get("action"), data.get("report_id"), data.get("reason")
        )
    except AdminServiceError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    durations = {"24h": 24 * 60 * 60, "7d": 7 * 24 * 60 * 60}

    with get_db() as conn:
        target = conn.execute("SELECT id, is_admin FROM users WHERE id = %s", (user_id,)).fetchone()
        if not target:
            return jsonify({"success": False, "error": "사용자를 찾을 수 없습니다."}), 404
        if target["is_admin"] or user_id == session["user_id"]:
            return (
                jsonify({"success": False, "error": "관리자 계정은 정지 처리할 수 없습니다."}),
                403,
            )

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

    # 이미 열려 있는 탭도 다음 요청부터 차단되고, 실시간 연결도 끊어 온라인 표시가 남지 않는다.
    if action in {"24h", "7d", "permanent"}:
        with active_socket_ids_lock:
            active_socket_ids.pop(user_id, None)
        emit_safe("account_suspended", {"reason": reason}, room=f"user_{user_id}")
    return jsonify({"success": True, "action": action})


@admin_required_api
def admin_delete_user(user_id):
    """계정을 완전히 삭제한다(하드 삭제). 메시지·체스 초대·친구 관계 등 본인 소유 데이터는
    DB 외래키(ON DELETE CASCADE)에 따라 함께 삭제되며, 되돌릴 수 없다."""
    with get_db() as conn:
        target = conn.execute("SELECT id, is_admin FROM users WHERE id = %s", (user_id,)).fetchone()
        if not target:
            return jsonify({"success": False, "error": "사용자를 찾을 수 없습니다."}), 404
        if target["is_admin"] or user_id == session["user_id"]:
            return jsonify({"success": False, "error": "관리자 계정은 삭제할 수 없습니다."}), 403
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

    with active_socket_ids_lock:
        active_socket_ids.pop(user_id, None)
    emit_safe("account_deleted", {}, room=f"user_{user_id}")
    return jsonify({"success": True})


# ----------------------------------------------------------------
# 대화방(conversations) API
# ----------------------------------------------------------------


@login_required_api
def get_conversations():
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
                    "_sortKey": row["last_activity_id"] or last_msg_id,
                }
            )
        result.sort(key=lambda r: (r["isPinned"], r["_sortKey"]), reverse=True)
        return jsonify(result)


@login_required_api
def create_group_conversation():
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
    """채팅 테마는 대화방 공용 설정으로 저장하고 모든 멤버에게 알린다."""
    theme = (request.get_json() or {}).get("theme", "default")
    user_id = session["user_id"]
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
    """채팅방 고정·알림 끄기는 사용자별 설정이므로 멤버 테이블에만 저장한다."""
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
    user_id = session["user_id"]
    if not chat_service.hide_conversation(conversation_id, user_id):
        return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404
    return jsonify({"success": True})


@login_required_api
def get_conversation_members(conversation_id):
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


# ----------------------------------------------------------------
# 메시지 API
# ----------------------------------------------------------------


@login_required_api
def link_preview():
    url = (request.get_json() or {}).get("url", "").strip()
    preview = get_link_preview(url)
    return jsonify({"success": bool(preview), "preview": preview})


@login_required_api
def get_messages(conversation_id):
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
        member_last_read = {m["user_id"]: m["last_read_message_id"] for m in member_read_rows}

        sender_names = {}
        sender_images = {}
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
    user_id = session["user_id"]
    data = request.get_json() or {}
    reply = data.get("reply")

    # 이 라우트는 텍스트 전용이다(사진·동영상·파일·음성은 별도 라우트를 쓴다).
    # 클라이언트 쪽 trim() 검사는 콘솔·직접 API 호출로 우회할 수 있으므로 서버에서도 반드시 검증한다.
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "메시지 내용을 입력해주세요."}), 400
    if len(text) > 5000:
        return jsonify({"success": False, "error": "메시지는 5,000자 이하로 입력해주세요."}), 400

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        if conversation_is_disabled(conn, conversation_id):
            return (
                jsonify(
                    {"success": False, "error": "종료된 채팅방에서는 새 메시지를 보낼 수 없습니다."}
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
            (new_message_id, conversation_id, user_id),
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id),
        )

        unhide_conversation(conn, conversation_id)

        conn.commit()
        notify_conversation_message(conn, conversation_id, user_id, text[:120])
        broadcast_to_conversation(
            conn, conversation_id, "conversation_updated", {"conversationId": conversation_id}
        )
        return jsonify({"success": True})


@login_required_api
def send_image(conversation_id):
    user_id = session["user_id"]
    data = request.get_json() or {}
    image_data_url = data.get("image")

    if not image_data_url or not image_data_url.startswith("data:image"):
        return jsonify({"success": False, "error": "올바른 이미지 데이터가 아닙니다."}), 400

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


ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}


def is_allowed_video(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


@login_required_api
def send_video(conversation_id):
    user_id = session["user_id"]

    video_file = request.files.get("video")
    if video_file:
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
    user_id = session["user_id"]
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"success": False, "error": "파일을 선택해주세요."}), 400

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
    user_id = session["user_id"]
    audio_file = request.files.get("audio")
    if not audio_file or not audio_file.filename:
        return jsonify({"success": False, "error": "음성 파일을 찾을 수 없습니다."}), 400
    if os.path.splitext(audio_file.filename)[1].lower() not in {".webm", ".ogg", ".mp4", ".m4a"}:
        return jsonify({"success": False, "error": "지원하지 않는 음성 형식입니다."}), 400
    try:
        duration = float(request.form.get("duration", "0"))
    except ValueError:
        duration = 0
    if duration <= 0 or duration > 30:
        return (
            jsonify({"success": False, "error": "음성 메시지는 최대 30초까지 보낼 수 있습니다."}),
            400,
        )
    with get_db() as conn:
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
    """프로필 카드에서 특정 메시지가 아니라 사용자 자체를 신고할 때 쓴다."""
    reporter_id = session["user_id"]
    if user_id == reporter_id:
        return jsonify({"success": False, "error": "본인은 신고할 수 없습니다."}), 400
    data = request.get_json() or {}
    reason = (data.get("reason") or "").strip()
    detail = (data.get("detail") or "").strip()
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

    delete_image_file(image_path)
    return jsonify({"success": True})


@login_required_api
def pin_message(message_id):
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
    if old_image and old_image != new_path:
        delete_image_file(old_image)
    return jsonify({"success": True, "cover_image": new_path})


@app.route("/api/users/<int:user_id>/profile", methods=["GET"])
@login_required_api
def public_profile(user_id):
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
    profile.pop("is_suspended", None)
    return jsonify({"success": True, **profile, "is_online": is_user_online(user_id)})


@app.route("/api/users/search", methods=["GET"])
@login_required_api
def search_user_profile():
    username = (request.args.get("username") or "").strip().lower()
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


@app.route("/api/account/username", methods=["PATCH"])
@login_required_api
def update_username():
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
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"success": False, "error": "현재 비밀번호가 일치하지 않습니다."})

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
    user_id = session["user_id"]
    data = request.get_json() or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    password_confirmation = (
        data.get("password_confirmation") or data.get("new_password_confirmation") or ""
    )

    if password_confirmation and new_password != password_confirmation:
        return jsonify({"success": False, "error": "비밀번호 확인이 일치하지 않습니다."}), 400

    if not PasswordPolicy.is_valid(new_password):
        return jsonify({"success": False, "error": PasswordPolicy.error_message()})

    with get_db() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"success": False, "error": "현재 비밀번호가 일치하지 않습니다."})

        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new_password), user_id),
        )
        conn.commit()

    return jsonify({"success": True})


@app.route("/api/account", methods=["DELETE"])
@login_required_api
def delete_account():
    user_id = session["user_id"]
    data = request.get_json() or {}
    password = data.get("password") or ""

    with get_db() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], password):
            return jsonify({"success": False, "error": "비밀번호가 일치하지 않습니다."})

        image_rows = conn.execute(
            "SELECT image FROM messages WHERE sender_id = %s AND image IS NOT NULL", (user_id,)
        ).fetchall()

        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

    for row in image_rows:
        delete_image_file(row["image"])

    session.clear()
    return jsonify({"success": True})


@app.route("/api/account/profile-image", methods=["PATCH"])
@login_required_api
def update_profile_image():
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

    if old and old["profile_image"] and old["profile_image"] != DEFAULT_PROFILE_IMAGE:
        delete_image_file(old["profile_image"])

    session["profile_image"] = new_path
    return jsonify({"success": True, "profile_image": new_path})


@app.route("/api/account/profile-image", methods=["DELETE"])
@login_required_api
def delete_profile_image():
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


def email_copy(kind, language, code=None, username=None):
    """인증 관련 메일은 화면 언어와 같은 언어로 보내되, 인증 코드는 항상 눈에 띄게 유지한다."""
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
    return copies.get(language, copies["ko"])[kind]


def send_verification_email(email, code):
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
    """Resend에서 인증한 발신 주소만 사용해 메일이 조용히 실패하지 않게 한다."""
    sender = os.environ.get("RESEND_FROM_EMAIL")
    if not sender:
        raise RuntimeError("RESEND_FROM_EMAIL 환경변수가 설정되지 않았습니다.")
    return sender


def send_password_reset_email(email, code):
    subject, html = email_copy("reset", get_interface_language(), code=code)
    resend.Emails.send(
        {
            "from": get_resend_sender(),
            "to": email,
            "subject": subject,
            "html": html,
        }
    )


@app.route("/api/password-reset/send-code", methods=["POST"])
@rate_limit(5, 15 * 60, "password_reset_email")
def send_password_reset_code():
    email = (request.get_json() or {}).get("email", "").strip().lower()

    # 계정 존재 여부를 노출하지 않는 공통 안내 문구
    message = "입력한 이메일로 가입된 계정이 있다면 인증 코드를 보냈습니다."

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": True, "message": message})

    with get_db() as conn:
        user = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()

        if not user:
            return jsonify({"success": True, "message": message})

        code = f"{random.randint(0, 999999):06d}"
        kst = timezone(timedelta(hours=9))
        expires_at = (datetime.now(kst) + timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")

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
        app.logger.exception("비밀번호 재설정 메일 발송 실패")
        # 이전에는 실패해도 성공 문구를 돌려줘서 사용자가 원인을 알 수 없었다.
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
    """비밀번호 변경 전에 재설정 인증번호만 먼저 확인한다."""
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
    if reset_code["expires_at"] < now_str():
        return (
            jsonify({"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."}),
            400,
        )
    return jsonify({"success": True, "message": "이메일 인증이 완료되었습니다."})


@app.route("/api/password-reset/confirm", methods=["POST"])
@rate_limit(8, 15 * 60, "password_reset_confirm")
def confirm_password_reset():
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

        conn.execute(
            "UPDATE users SET password_hash = %s WHERE email = %s",
            (generate_password_hash(new_password), email),
        )
        conn.execute("DELETE FROM password_reset_codes WHERE email = %s", (email,))
        conn.commit()

    return jsonify({"success": True})


def send_username_reminder_email(email, username):
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
    email = (request.get_json() or {}).get("email", "").strip().lower()

    # 이메일 형식이 틀려도 동일한 응답을 보내 계정 존재 여부를 감춥니다.
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
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."}), 400

    with get_db() as conn:
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
    """회원가입 전 인증번호를 미리 확인해 사용자에게 완료 상태를 보여준다."""
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
    user_id = session["user_id"]
    data = request.get_json() or {}
    new_email = (data.get("email") or "").strip().lower()

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", new_email):
        return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."}), 400

    with get_db() as conn:
        # 내 계정 제외하고 이미 쓰이는 이메일인지 체크
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

        # 코드 발송 이후 다른 사람이 선점했을 수도 있으니 한 번 더 체크
        existing = conn.execute(
            "SELECT id FROM users WHERE email = %s AND id != %s", (new_email, user_id)
        ).fetchone()
        if existing:
            return jsonify({"success": False, "error": "이미 사용 중인 이메일입니다."})

        conn.execute(
            "UPDATE users SET email = %s, is_admin = %s WHERE id = %s",
            (new_email, bool(ADMIN_EMAIL and new_email == ADMIN_EMAIL), user_id),
        )
        conn.execute("DELETE FROM email_verification_codes WHERE email = %s", (new_email,))
        conn.commit()

    session["email"] = new_email
    return jsonify({"success": True, "email": new_email})


@login_required_api
def read_conversation(conversation_id):
    user_id = session["user_id"]
    if not chat_service.mark_read(conversation_id, user_id):
        return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404
    return jsonify({"success": True})


# ----------------------------------------------------------------
# 체스: 서버 권위 상태 관리 (클라이언트 FEN은 화면 표시용일 뿐, 수 판정에는 사용하지 않음)
# ----------------------------------------------------------------
CHESS_TIME_CONTROLS = {
    "unlimited": None,
    "blitz3": 3 * 60 * 1000,
    "blitz5": 5 * 60 * 1000,
    "rapid10": 10 * 60 * 1000,
}
CHESS_WAITING_PLAYER = {
    "id": None,
    "name": "대기 중",
    "username": "",
    "profileImage": None,
    "rating": None,
    "record": {"wins": 0, "draws": 0, "losses": 0},
}


def chess_room_code(conn):
    while True:
        code = secrets.token_hex(3).upper()
        if not conn.execute("SELECT 1 FROM chess_games WHERE room_code = %s", (code,)).fetchone():
            return code


def create_chess_game(conn, user_id, mode, time_control="unlimited", color="w"):
    if mode != "online":
        raise ValueError("온라인 대전만 지원합니다.")
    if time_control not in CHESS_TIME_CONTROLS:
        time_control = "unlimited"
    if color not in ("w", "b"):
        color = "w"
    game_id, room_code = str(uuid.uuid4()), chess_room_code(conn)
    clock = CHESS_TIME_CONTROLS[time_control]
    # 방장이 미리 고른 색으로 자기 자리를 채우고, 반대쪽 자리는 입장할 상대를 위해 비워둔다.
    white_id = user_id if color == "w" else None
    black_id = user_id if color == "b" else None
    conn.execute(
        """
        INSERT INTO chess_games (
            id, room_code, white_player_id, black_player_id, mode, fen, status, time_control,
            white_remaining_ms, black_remaining_ms, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, 'waiting', %s, %s, %s, %s, %s)
    """,
        (
            game_id,
            room_code,
            white_id,
            black_id,
            mode,
            STARTING_FEN,
            time_control,
            clock,
            clock,
            now_str(),
            now_str(),
        ),
    )
    return conn.execute("SELECT * FROM chess_games WHERE id = %s", (game_id,)).fetchone()


def chess_player_summary(conn, user_id):
    """메신저의 프로필 카드 정보에 체스 레이팅과 전적을 덧붙여 재사용한다. user_id는 항상 실제 계정이어야 한다."""
    user = conn.execute(
        "SELECT id, username, display_name, profile_image, chess_rating, chess_wins, chess_draws, chess_losses FROM users WHERE id = %s",
        (user_id,),
    ).fetchone()
    if not user:
        return {
            "id": user_id,
            "name": "알 수 없음",
            "username": "",
            "profileImage": DEFAULT_PROFILE_IMAGE,
            "rating": 400,
            "record": {"wins": 0, "draws": 0, "losses": 0},
        }
    return {
        "id": user["id"],
        "name": user["display_name"] or user["username"],
        "username": user["username"],
        "profileImage": user["profile_image"] or DEFAULT_PROFILE_IMAGE,
        "rating": user["chess_rating"] or 400,
        "record": {
            "wins": user["chess_wins"] or 0,
            "draws": user["chess_draws"] or 0,
            "losses": user["chess_losses"] or 0,
        },
    }


def refresh_chess_clock(conn, game):
    """서버 시각으로만 남은 시간을 깎아 브라우저 시간 조작을 막는다."""
    if (
        game["status"] != "active"
        or game["time_control"] == "unlimited"
        or not game["turn_started_ms"]
    ):
        return game
    now = current_message_timestamp_ms()
    elapsed = max(0, now - game["turn_started_ms"])
    key = "white_remaining_ms" if ChessBoard(game["fen"]).turn == "w" else "black_remaining_ms"
    remaining = max(0, (game[key] or 0) - elapsed)
    if remaining == 0:
        winner = "b" if key == "white_remaining_ms" else "w"
        result = {"status": "timeout", "winner": winner}
        conn.execute(
            "UPDATE chess_games SET %s = %%s, status = 'finished', result = %%s, updated_at = %%s WHERE id = %%s"
            % key,
            (0, json.dumps(result), now_str(), game["id"]),
        )
        emit_safe(
            "game:timeout",
            {"gameId": str(game["id"]), "winner": winner},
            room=f"chess_{game['id']}",
        )
    else:
        conn.execute(
            "UPDATE chess_games SET %s = %%s, turn_started_ms = %%s, updated_at = %%s WHERE id = %%s"
            % key,
            (remaining, now, now_str(), game["id"]),
        )
    return conn.execute("SELECT * FROM chess_games WHERE id = %s", (game["id"],)).fetchone()


def chess_board_for_game(conn, game):
    board = ChessBoard(game["fen"])
    rows = conn.execute(
        "SELECT san, fen FROM chess_game_moves WHERE game_id = %s ORDER BY move_number",
        (game["id"],),
    ).fetchall()
    board.san_history = [row["san"] for row in rows]
    # 재접속해도 3회 반복 판정이 초기화되지 않도록 각 수 뒤의 국면을 다시 센다.
    board.position_counts = Counter({ChessBoard(STARTING_FEN).position_key(): 1})
    for row in rows:
        board.position_counts[ChessBoard(row["fen"]).position_key()] += 1
    return board


def chess_game_state(conn, game, user_id=None):
    game = refresh_chess_clock(conn, game)
    game = apply_chess_ratings(conn, game)
    board = chess_board_for_game(conn, game)
    move_rows = conn.execute(
        "SELECT move_number, san, fen FROM chess_game_moves WHERE game_id = %s ORDER BY move_number",
        (game["id"],),
    ).fetchall()
    state = board.state()
    state.update(
        {
            "id": str(game["id"]),
            "roomCode": game["room_code"],
            "mode": game["mode"],
            "status": game["status"],
            "timeControl": game["time_control"],
            "whiteRemainingMs": game["white_remaining_ms"],
            "blackRemainingMs": game["black_remaining_ms"],
            "turnStartedMs": game["turn_started_ms"],
            "white": (
                chess_player_summary(conn, game["white_player_id"])
                if game["white_player_id"]
                else CHESS_WAITING_PLAYER
            ),
            "black": (
                chess_player_summary(conn, game["black_player_id"])
                if game["black_player_id"]
                else CHESS_WAITING_PLAYER
            ),
            "result": json.loads(game["result"]) if game["result"] else state["result"],
            "moves": [
                {"number": row["move_number"], "san": row["san"], "fen": row["fen"]}
                for row in move_rows
            ],
            "myColor": (
                "w"
                if user_id == game["white_player_id"]
                else ("b" if user_id == game["black_player_id"] else None)
            ),
            "canPlay": bool(
                user_id and user_id in {game["white_player_id"], game["black_player_id"]}
            ),
            # 방 전체로 방송되는 상태이므로 "누가 제안했는지"는 순수 id로만 보내고,
            # 나 기준 판단(내가 걸었는지/상대가 걸었는지)은 각 클라이언트가 currentUserId와 비교해 계산한다.
            "drawOfferedBy": game["draw_offer_user_id"],
        }
    )
    chats = conn.execute(
        "SELECT chat.sender_id, users.display_name, users.username, chat.text FROM chess_game_chat_messages chat JOIN users ON users.id = chat.sender_id WHERE chat.game_id = %s ORDER BY chat.id DESC LIMIT 40",
        (game["id"],),
    ).fetchall()
    state["chatMessages"] = [dict(row) for row in reversed(chats)]
    return state


def apply_chess_ratings(conn, game):
    """온라인 대국의 종료 결과만 한 번 ELO 방식으로 반영한다."""
    if (
        game["mode"] != "online"
        or game["status"] != "finished"
        or game["ratings_applied"]
        or not game["white_player_id"]
        or not game["black_player_id"]
    ):
        return game
    result = json.loads(game["result"] or "{}")
    if result.get("status") not in {
        "checkmate",
        "resignation",
        "timeout",
        "disconnect",
        "stalemate",
        "draw_50_move",
        "draw_threefold",
        "draw_insufficient_material",
        "draw_agreed",
    }:
        return game
    rows = conn.execute(
        "SELECT id, chess_rating FROM users WHERE id IN (%s, %s)",
        (game["white_player_id"], game["black_player_id"]),
    ).fetchall()
    ratings = {row["id"]: row["chess_rating"] for row in rows}
    white, black = ratings[game["white_player_id"]], ratings[game["black_player_id"]]
    winner = result.get("winner")
    expected = 1 / (1 + 10 ** ((black - white) / 400))
    score = 1 if winner == "w" else 0 if winner == "b" else 0.5
    change = round(24 * (score - expected))
    result["ratingChanges"] = {"white": change, "black": -change}
    # 전적(승/무/패)도 레이팅처럼 계정에 직접 누적해, 기보를 삭제해도 프로필 전적은 그대로 남는다.
    white_column = (
        "chess_wins" if winner == "w" else "chess_draws" if winner is None else "chess_losses"
    )
    black_column = (
        "chess_wins" if winner == "b" else "chess_draws" if winner is None else "chess_losses"
    )
    conn.execute(
        f"UPDATE users SET chess_rating = chess_rating + %s, {white_column} = {white_column} + 1 WHERE id = %s",
        (change, game["white_player_id"]),
    )
    conn.execute(
        f"UPDATE users SET chess_rating = chess_rating - %s, {black_column} = {black_column} + 1 WHERE id = %s",
        (change, game["black_player_id"]),
    )
    conn.execute(
        "UPDATE chess_games SET ratings_applied = TRUE, result = %s WHERE id = %s",
        (json.dumps(result), game["id"]),
    )
    return conn.execute("SELECT * FROM chess_games WHERE id = %s", (game["id"],)).fetchone()


def chess_can_control_turn(game, user_id, turn):
    return user_id == (game["white_player_id"] if turn == "w" else game["black_player_id"])


def save_chess_move(conn, game, board, move):
    san = board.push(move)
    move_number = len(board.san_history)
    result = board.result()
    status = "finished" if result["status"] != "active" else "active"
    conn.execute(
        "INSERT INTO chess_game_moves (game_id, move_number, san, fen, created_at) VALUES (%s, %s, %s, %s, %s)",
        (game["id"], move_number, san, board.fen(), now_str()),
    )
    conn.execute(
        """
        UPDATE chess_games SET fen = %s, status = %s, result = %s, draw_offer_user_id = NULL,
            turn_started_ms = %s, updated_at = %s WHERE id = %s
    """,
        (
            board.fen(),
            status,
            json.dumps(result) if status == "finished" else None,
            current_message_timestamp_ms() if status == "active" else None,
            now_str(),
            game["id"],
        ),
    )
    return conn.execute("SELECT * FROM chess_games WHERE id = %s", (game["id"],)).fetchone(), san


def submit_chess_move(conn, game, user_id, from_sq, to_sq, promotion=None):
    game = refresh_chess_clock(conn, game)
    if game["status"] != "active":
        raise ValueError("진행 중인 게임이 아닙니다.")
    board = chess_board_for_game(conn, game)
    if not chess_can_control_turn(game, user_id, board.turn):
        raise ValueError("현재 차례가 아닙니다.")
    move = board.find_move(from_sq, to_sq, promotion)
    game, _ = save_chess_move(conn, game, board, move)
    return game


def activate_chess_game(conn, game, joining_user_id):
    """대기 중인 온라인 방에 두 번째 사용자를 넣는다. 방장이 미리 고른 색의 반대쪽 자리를 받는다."""
    if game["mode"] != "online" or game["status"] != "waiting":
        raise ValueError("입장할 수 있는 대기 방이 아닙니다.")
    if joining_user_id in {game["white_player_id"], game["black_player_id"]}:
        raise ValueError("만든 방에는 다른 계정으로 입장해 주세요.")
    white_id = joining_user_id if game["white_player_id"] is None else game["white_player_id"]
    black_id = joining_user_id if game["black_player_id"] is None else game["black_player_id"]
    conn.execute(
        """
        UPDATE chess_games SET white_player_id = %s, black_player_id = %s, status = 'active',
            turn_started_ms = %s, disconnected_user_id = NULL, disconnect_deadline_ms = NULL, updated_at = %s WHERE id = %s
    """,
        (white_id, black_id, current_message_timestamp_ms(), now_str(), game["id"]),
    )
    return conn.execute("SELECT * FROM chess_games WHERE id = %s", (game["id"],)).fetchone()


def chess_game_or_404(conn, game_id):
    game = conn.execute("SELECT * FROM chess_games WHERE id = %s", (game_id,)).fetchone()
    if not game:
        abort(404)
    return game


def mark_chess_disconnect(user_id):
    """마지막 브라우저 연결이 끊긴 온라인 참가자에게만 60초 재접속 유예를 둔다."""
    deadline = current_message_timestamp_ms() + 60_000
    with get_db() as conn:
        games = conn.execute(
            """
            SELECT * FROM chess_games WHERE mode = 'online' AND status = 'active'
            AND (white_player_id = %s OR black_player_id = %s)
        """,
            (user_id, user_id),
        ).fetchall()
        for game in games:
            conn.execute(
                "UPDATE chess_games SET disconnected_user_id = %s, disconnect_deadline_ms = %s WHERE id = %s",
                (user_id, deadline, game["id"]),
            )
            socketio.start_background_task(
                finalize_chess_disconnect, str(game["id"]), user_id, deadline
            )
        conn.commit()


def finalize_chess_disconnect(game_id, user_id, deadline):
    socketio.sleep(60)
    with get_db() as conn:
        game = conn.execute("SELECT * FROM chess_games WHERE id = %s", (game_id,)).fetchone()
        if (
            not game
            or game["status"] != "active"
            or game["disconnected_user_id"] != user_id
            or game["disconnect_deadline_ms"] != deadline
        ):
            return
        color = "w" if game["white_player_id"] == user_id else "b"
        result = {"status": "disconnect", "winner": opponent(color)}
        conn.execute(
            "UPDATE chess_games SET status = 'finished', result = %s, updated_at = %s WHERE id = %s",
            (json.dumps(result), now_str(), game_id),
        )
        game = chess_game_or_404(conn, game_id)
        state = chess_game_state(conn, game)
        conn.commit()
    emit_safe("game:state_update", state, room=f"chess_{game_id}")


@app.route("/chess")
@login_required_page
def chess_lobby_page():
    return render_template("chess_lobby.html")


@app.route("/chess/game/<game_id>")
@login_required_page
def chess_game_page(game_id):
    return render_template("chess_game.html", game_id=game_id)


def chess_invitable_friends(conn, user_id):
    """1:1 채팅방으로 연결된 친구만 체스 대국 초대 대상으로 반환한다."""
    return conn.execute(
        """
        SELECT DISTINCT users.id, users.display_name, users.username, users.profile_image, conversations.id AS conversation_id,
               COALESCE(users.display_name, users.username) AS sort_name
        FROM conversations
        JOIN conversation_members mine ON mine.conversation_id = conversations.id AND mine.user_id = %s
        JOIN conversation_members peer_member ON peer_member.conversation_id = conversations.id AND peer_member.user_id != %s
        JOIN users ON users.id = peer_member.user_id
        WHERE conversations.is_group = FALSE
          AND NOT EXISTS (SELECT 1 FROM blocks WHERE (blocker_id = %s AND blocked_id = users.id) OR (blocker_id = users.id AND blocked_id = %s))
        -- PostgreSQL의 DISTINCT 정렬 규칙을 지켜 초대 목록 API가 HTML 오류 페이지로 떨어지지 않게 한다.
        ORDER BY sort_name
    """,
        (user_id, user_id, user_id, user_id),
    ).fetchall()


@app.route("/api/chess/games/<game_id>/inviteable-friends")
@login_required_api
def chess_invitable_friends_api(game_id):
    with get_db() as conn:
        game = chess_game_or_404(conn, game_id)
        if (
            game["mode"] != "online"
            or game["status"] != "waiting"
            or session["user_id"] not in {game["white_player_id"], game["black_player_id"]}
        ):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "대기 중인 온라인 방장만 친구를 초대할 수 있습니다.",
                    }
                ),
                403,
            )
        friends = chess_invitable_friends(conn, session["user_id"])
    return jsonify({"success": True, "friends": [dict(friend) for friend in friends]})


@app.route("/api/chess/games/<game_id>/invites", methods=["POST"])
@login_required_api
def chess_send_invite_api(game_id):
    invitee_id = (request.get_json() or {}).get("userId")
    try:
        invitee_id = int(invitee_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "초대할 친구를 선택해주세요."}), 400
    with get_db() as conn:
        game = chess_game_or_404(conn, game_id)
        user_id = session["user_id"]
        if (
            game["mode"] != "online"
            or game["status"] != "waiting"
            or user_id not in {game["white_player_id"], game["black_player_id"]}
        ):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "대기 중인 온라인 방장만 친구를 초대할 수 있습니다.",
                    }
                ),
                403,
            )
        friends = {friend["id"]: friend for friend in chess_invitable_friends(conn, user_id)}
        if invitee_id not in friends:
            return jsonify({"success": False, "error": "친구만 초대할 수 있습니다."}), 403
        invite = conn.execute(
            """
            INSERT INTO chess_invites (game_id, inviter_id, invitee_id, status, created_at)
            VALUES (%s, %s, %s, 'pending', %s)
            ON CONFLICT (game_id, invitee_id) DO UPDATE SET status = 'pending', created_at = EXCLUDED.created_at
            RETURNING id
        """,
            (game_id, user_id, invitee_id, now_str()),
        ).fetchone()
        conn.commit()
    # 초대는 채팅방 링크가 아니라 체스 페이지의 메시지함에서만 수락/거절하도록 한다.
    notify_user(invitee_id, "chess_invite", {"gameId": str(game_id), "inviteId": invite["id"]})
    return jsonify({"success": True})


@app.route("/api/chess/invites/<int:invite_id>/accept", methods=["POST"])
@login_required_api
def chess_accept_invite_api(invite_id):
    with get_db() as conn:
        invite = conn.execute("SELECT * FROM chess_invites WHERE id = %s", (invite_id,)).fetchone()
        if (
            not invite
            or invite["invitee_id"] != session["user_id"]
            or invite["status"] != "pending"
        ):
            return (
                jsonify(
                    {"success": False, "error": "유효하지 않거나 이미 처리된 체스 초대입니다."}
                ),
                404,
            )
        game = chess_game_or_404(conn, invite["game_id"])
        if game["mode"] != "online" or game["status"] != "waiting":
            return (
                jsonify(
                    {"success": False, "error": "이 체스 방은 이미 시작되었거나 종료되었습니다."}
                ),
                400,
            )
        game = activate_chess_game(conn, game, session["user_id"])
        conn.execute(
            "UPDATE chess_invites SET status = CASE WHEN id = %s THEN 'accepted' ELSE 'expired' END WHERE game_id = %s AND status = 'pending'",
            (invite_id, game["id"]),
        )
        state = chess_game_state(conn, game, session["user_id"])
        conn.commit()
    emit_safe("game:start", state, room=f"chess_{game['id']}")
    return jsonify({"success": True, "game": state})


@app.route("/api/chess/invites", methods=["GET"])
@login_required_api
def chess_inbox_invites_api():
    """체스 초대는 일반 팝업이 아니라 기존 메시지함에서 처리할 수 있도록 별도로 제공한다."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT i.id, i.created_at, g.id AS game_id, g.time_control, g.room_code,
                   u.id AS inviter_id, u.username, u.display_name, u.profile_image, u.chess_rating
            FROM chess_invites i
            JOIN chess_games g ON g.id = i.game_id
            JOIN users u ON u.id = i.inviter_id
            WHERE i.invitee_id = %s AND i.status = 'pending' AND g.status = 'waiting'
            ORDER BY i.created_at DESC
        """,
            (session["user_id"],),
        ).fetchall()
    return jsonify({"success": True, "invites": [dict(row) for row in rows]})


@app.route("/api/chess/invites/<int:invite_id>/decline", methods=["POST"])
@login_required_api
def chess_decline_invite_api(invite_id):
    with get_db() as conn:
        invite = conn.execute(
            "SELECT * FROM chess_invites WHERE id = %s AND invitee_id = %s AND status = 'pending'",
            (invite_id, session["user_id"]),
        ).fetchone()
        if not invite:
            return jsonify({"success": False, "error": "처리할 수 없는 체스 초대입니다."}), 404
        conn.execute("UPDATE chess_invites SET status = 'declined' WHERE id = %s", (invite_id,))
        conn.commit()
    notify_user(
        invite["inviter_id"], "chess_invite_updated", {"inviteId": invite_id, "status": "declined"}
    )
    return jsonify({"success": True})


@app.route("/api/chess/players/<int:player_id>")
@login_required_api
def chess_player_profile_api(player_id):
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, profile_visibility, is_suspended FROM users WHERE id = %s", (player_id,)
        ).fetchone()
        if not user:
            return jsonify({"success": False, "error": "사용자를 찾을 수 없습니다."}), 404
        shared_game = conn.execute(
            """
            SELECT 1 FROM chess_games
            WHERE (white_player_id = %s OR black_player_id = %s)
              AND (white_player_id = %s OR black_player_id = %s)
            LIMIT 1
        """,
            (session["user_id"], session["user_id"], player_id, player_id),
        ).fetchone()
        if (
            player_id != session["user_id"]
            and not shared_game
            and not can_view_profile(conn, session["user_id"], user)
        ):
            return (
                jsonify({"success": False, "error": "이 사용자는 프로필을 비공개로 설정했습니다."}),
                403,
            )
        summary = chess_player_summary(conn, player_id)
        is_friend = are_users_friends(conn, session["user_id"], player_id)
    return jsonify({"success": True, "player": {**summary, "isFriend": is_friend}})


@app.route("/api/chess/players/<int:player_id>/friend-request", methods=["POST"])
@login_required_api
def chess_send_friend_request_api(player_id):
    """체스 프로필 카드에서도 메신저 친구 요청과 같은 테이블/규칙을 재사용한다."""
    user_id = session["user_id"]
    if player_id == user_id:
        return (
            jsonify({"success": False, "error": "자기 자신에게 친구 요청을 보낼 수 없습니다."}),
            400,
        )
    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id = %s", (player_id,)).fetchone()
        if not target or is_blocked_either_way(conn, user_id, player_id):
            return (
                jsonify({"success": False, "error": "친구 요청을 보낼 수 없는 사용자입니다."}),
                403,
            )
        if are_users_friends(conn, user_id, player_id):
            return jsonify({"success": False, "error": "이미 친구입니다."}), 400
        reverse = conn.execute(
            "SELECT id FROM friend_requests WHERE requester_id = %s AND addressee_id = %s AND status = 'pending'",
            (player_id, user_id),
        ).fetchone()
        if reverse:
            accept_friend_request(conn, reverse["id"])
            message = "서로 친구가 되었습니다."
        else:
            conn.execute(
                """
                INSERT INTO friend_requests (requester_id, addressee_id, status, created_at)
                VALUES (%s, %s, 'pending', %s)
                ON CONFLICT (requester_id, addressee_id) DO UPDATE SET status = 'pending', created_at = EXCLUDED.created_at
            """,
                (user_id, player_id, now_str()),
            )
            message = "친구 요청을 보냈습니다."
        conn.commit()
    notify_user(player_id, "friend_updated", {})
    return jsonify({"success": True, "message": message})


@app.route("/api/chess/games", methods=["POST"])
@login_required_api
def chess_create_game_api():
    data = request.get_json() or {}
    with get_db() as conn:
        game = create_chess_game(
            conn,
            session["user_id"],
            data.get("mode", "online"),
            data.get("timeControl", "unlimited"),
            data.get("color", "w"),
        )
        state = chess_game_state(conn, game, session["user_id"])
        conn.commit()
    return jsonify({"success": True, "game": state})


@app.route("/api/chess/quick-invite/<int:friend_id>", methods=["POST"])
@login_required_api
def chess_quick_invite_friend_api(friend_id):
    """메신저 친구 목록에서 온라인 체스방을 만들고 해당 친구에게 즉시 초대한다."""
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    time_control = data.get("timeControl", "unlimited")

    with get_db() as conn:
        # 실제 친구 관계인지 확인한다.
        if not are_users_friends(conn, user_id, friend_id):
            return (
                jsonify({"success": False, "error": "친구에게만 체스 초대를 보낼 수 있습니다."}),
                403,
            )

        # 차단 관계가 있으면 초대를 보내지 않는다.
        if is_blocked_either_way(conn, user_id, friend_id):
            return (
                jsonify(
                    {"success": False, "error": "차단된 사용자에게는 체스 초대를 보낼 수 없습니다."}
                ),
                403,
            )

        # 상대 친구의 1:1 대화방을 먼저 확인한다.
        # 모든 권한 검사를 통과한 뒤에만 대기방을 생성해 불필요한 chess_games 행이 남지 않게 한다.
        friends = {friend["id"]: friend for friend in chess_invitable_friends(conn, user_id)}

        friend = friends.get(friend_id)
        if not friend:
            return (
                jsonify({"success": False, "error": "체스 초대를 보낼 수 있는 친구가 아닙니다."}),
                403,
            )

        # 모든 권한 검사를 통과한 뒤 온라인 대기방 생성
        game = create_chess_game(
            conn,
            user_id,
            "online",
            time_control,
        )

        invite = conn.execute(
            """
            INSERT INTO chess_invites (
                game_id,
                inviter_id,
                invitee_id,
                status,
                created_at
            )
            VALUES (%s, %s, %s, 'pending', %s)
            RETURNING id
        """,
            (
                game["id"],
                user_id,
                friend_id,
                now_str(),
            ),
        ).fetchone()

        state = chess_game_state(conn, game, user_id)
        conn.commit()

    # 초대는 채팅방 링크가 아니라 체스 페이지의 메시지함에서만 수락/거절하도록 한다.
    notify_user(
        friend_id,
        "chess_invite",
        {
            "gameId": str(game["id"]),
            "inviteId": invite["id"],
        },
    )

    return jsonify(
        {
            "success": True,
            "game": state,
            "inviteId": invite["id"],
        }
    )


@app.route("/api/chess/games/<game_id>")
@login_required_api
def chess_game_state_api(game_id):
    with get_db() as conn:
        game = chess_game_or_404(conn, game_id)
        if session["user_id"] not in {game["white_player_id"], game["black_player_id"]}:
            return jsonify({"success": False, "error": "이 게임을 볼 권한이 없습니다."}), 403
        state = chess_game_state(conn, game, session["user_id"])
        conn.commit()
    return jsonify({"success": True, "game": state})


@app.route("/api/chess/history")
@login_required_api
def chess_history_api():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, mode, result, status, created_at, white_player_id, black_player_id FROM chess_games
            WHERE status = 'finished' AND (white_player_id = %s OR black_player_id = %s)
            ORDER BY created_at DESC LIMIT 5
        """,
            (session["user_id"], session["user_id"]),
        ).fetchall()
    return jsonify(
        [
            {
                "id": str(row["id"]),
                "mode": row["mode"],
                "status": row["status"],
                "result": json.loads(row["result"]) if row["result"] else None,
                "createdAt": row["created_at"],
                "myColor": "w" if row["white_player_id"] == session["user_id"] else "b",
            }
            for row in rows
        ]
    )


@app.route("/api/chess/history", methods=["DELETE"])
@login_required_api
def chess_delete_all_history_api():
    """현재 로그인 계정의 종료 전적만 삭제한다. 진행 중인 방과 레이팅은 보존한다."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM chess_games WHERE status = 'finished' AND (white_player_id = %s OR black_player_id = %s)",
            (session["user_id"], session["user_id"]),
        ).fetchall()
        game_ids = [row["id"] for row in rows]
        if not game_ids:
            return jsonify({"success": True, "deleted": 0})
        # UUID 배열임을 명시해 배포 DB에서도 전적·기보·채팅을 함께 안정적으로 삭제한다.
        conn.execute(
            "DELETE FROM chess_game_chat_messages WHERE game_id = ANY(%s::uuid[])", (game_ids,)
        )
        conn.execute("DELETE FROM chess_game_moves WHERE game_id = ANY(%s::uuid[])", (game_ids,))
        conn.execute("DELETE FROM chess_games WHERE id = ANY(%s::uuid[])", (game_ids,))
        conn.commit()
    return jsonify({"success": True, "deleted": len(game_ids)})


@app.route("/api/chess/history/<game_id>", methods=["DELETE"])
@login_required_api
def chess_delete_history_api(game_id):
    """진행 중인 대국은 보호하고, 끝난 본인 전적만 삭제한다."""
    with get_db() as conn:
        game = chess_game_or_404(conn, game_id)
        user_id = session["user_id"]
        if user_id not in {game["white_player_id"], game["black_player_id"]}:
            return jsonify({"success": False, "error": "본인 전적만 삭제할 수 있습니다."}), 403
        if game["status"] != "finished":
            return jsonify({"success": False, "error": "진행 중인 게임은 삭제할 수 없습니다."}), 400
        # 초기 배포 DB에 CASCADE 제약이 누락돼 있어도 전적 삭제가 막히지 않게 기보부터 명시적으로 정리한다.
        conn.execute("DELETE FROM chess_game_moves WHERE game_id = %s", (game_id,))
        conn.execute("DELETE FROM chess_games WHERE id = %s", (game_id,))
        conn.commit()
    return jsonify({"success": True})


@app.route("/api/chess/games/<game_id>/move", methods=["POST"])
@login_required_api
def chess_move_api(game_id):
    data = request.get_json() or {}
    try:
        with get_db() as conn:
            game = chess_game_or_404(conn, game_id)
            game = submit_chess_move(
                conn,
                game,
                session["user_id"],
                data.get("from", ""),
                data.get("to", ""),
                data.get("promotion"),
            )
            state = chess_game_state(conn, game, session["user_id"])
            conn.commit()
        emit_safe("game:state_update", state, room=f"chess_{game_id}")
        return jsonify({"success": True, "game": state})
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400


@app.route("/api/chess/games/<game_id>/resign", methods=["POST"])
@login_required_api
def chess_resign_api(game_id):
    with get_db() as conn:
        game = chess_game_or_404(conn, game_id)
        user_id = session["user_id"]
        if user_id not in {game["white_player_id"], game["black_player_id"]}:
            return jsonify({"success": False, "error": "참가자만 기권할 수 있습니다."}), 403
        color = "w" if user_id == game["white_player_id"] else "b"
        result = {"status": "resignation", "winner": opponent(color)}
        conn.execute(
            "UPDATE chess_games SET status = 'finished', result = %s, updated_at = %s WHERE id = %s",
            (json.dumps(result), now_str(), game_id),
        )
        game = chess_game_or_404(conn, game_id)
        state = chess_game_state(conn, game, user_id)
        conn.commit()
    emit_safe("game:state_update", state, room=f"chess_{game_id}")
    return jsonify({"success": True, "game": state})


@app.route("/api/chess/games/<game_id>/draw", methods=["POST", "DELETE"])
@login_required_api
def chess_draw_api(game_id):
    with get_db() as conn:
        game = chess_game_or_404(conn, game_id)
        user_id = session["user_id"]
        if user_id not in {game["white_player_id"], game["black_player_id"]}:
            return (
                jsonify({"success": False, "error": "참가자만 무승부를 제안할 수 있습니다."}),
                403,
            )
        if game["status"] != "active":
            return (
                jsonify(
                    {"success": False, "error": "진행 중인 게임에서만 무승부를 제안할 수 있습니다."}
                ),
                400,
            )
        if request.method == "DELETE":
            # 내가 건 제안은 취소하고, 상대가 건 제안은 거절한다. 어느 쪽이든 제안을 지운다.
            conn.execute(
                "UPDATE chess_games SET draw_offer_user_id = NULL, updated_at = %s WHERE id = %s",
                (now_str(), game_id),
            )
        elif game["draw_offer_user_id"] and game["draw_offer_user_id"] != user_id:
            result = {"status": "draw_agreed", "winner": None}
            conn.execute(
                "UPDATE chess_games SET status = 'finished', result = %s, draw_offer_user_id = NULL, updated_at = %s WHERE id = %s",
                (json.dumps(result), now_str(), game_id),
            )
        else:
            conn.execute(
                "UPDATE chess_games SET draw_offer_user_id = %s, updated_at = %s WHERE id = %s",
                (user_id, now_str(), game_id),
            )
        game = chess_game_or_404(conn, game_id)
        state = chess_game_state(conn, game, user_id)
        conn.commit()
    emit_safe("game:state_update", state, room=f"chess_{game_id}")
    return jsonify({"success": True, "game": state})


@app.route("/api/chess/join", methods=["POST"])
@login_required_api
def chess_join_game_api():
    code = (request.get_json() or {}).get("roomCode", "").strip().upper()
    with get_db() as conn:
        game = conn.execute("SELECT * FROM chess_games WHERE room_code = %s", (code,)).fetchone()
        if not game:
            return (
                jsonify({"success": False, "error": "입장할 수 있는 방 코드를 찾지 못했습니다."}),
                404,
            )
        try:
            game = activate_chess_game(conn, game, session["user_id"])
        except ValueError as error:
            return jsonify({"success": False, "error": str(error)}), 400
        state = chess_game_state(conn, game, session["user_id"])
        conn.commit()
    emit_safe("game:start", state, room=f"chess_{game['id']}")
    return jsonify({"success": True, "game": state})


@socketio.on("room:join")
def chess_socket_join(data):
    if "user_id" not in session:
        return
    game_id = (data or {}).get("gameId")
    if game_id:
        join_room(f"chess_{game_id}")


@socketio.on("room:create")
def chess_socket_create(data):
    if "user_id" not in session:
        return
    with get_db() as conn:
        game = create_chess_game(
            conn, session["user_id"], "online", (data or {}).get("timeControl", "unlimited")
        )
        state = chess_game_state(conn, game, session["user_id"])
        conn.commit()
    join_room(f"chess_{game['id']}")
    emit_safe("room:created", state, room=f"user_{session['user_id']}")


@socketio.on("game:move")
def chess_socket_move(data):
    if "user_id" not in session:
        return
    try:
        with get_db() as conn:
            game = chess_game_or_404(conn, (data or {}).get("gameId"))
            game = submit_chess_move(
                conn,
                game,
                session["user_id"],
                data.get("from", ""),
                data.get("to", ""),
                data.get("promotion"),
            )
            state = chess_game_state(conn, game, session["user_id"])
            conn.commit()
        emit_safe("game:state_update", state, room=f"chess_{game['id']}")
    except (ValueError, TypeError) as error:
        emit_safe("game:error", {"error": str(error)}, room=f"user_{session['user_id']}")


@socketio.on("game:resign")
def chess_socket_resign(data):
    if "user_id" not in session:
        return
    with get_db() as conn:
        game = chess_game_or_404(conn, (data or {}).get("gameId"))
        user_id = session["user_id"]
        if user_id not in {game["white_player_id"], game["black_player_id"]}:
            return
        color = "w" if user_id == game["white_player_id"] else "b"
        conn.execute(
            "UPDATE chess_games SET status = 'finished', result = %s, updated_at = %s WHERE id = %s",
            (
                json.dumps({"status": "resignation", "winner": opponent(color)}),
                now_str(),
                game["id"],
            ),
        )
        game = chess_game_or_404(conn, game["id"])
        state = chess_game_state(conn, game, user_id)
        conn.commit()
    emit_safe("game:state_update", state, room=f"chess_{game['id']}")


@socketio.on("game:offer_draw")
def chess_socket_offer_draw(data):
    if "user_id" not in session:
        return
    with get_db() as conn:
        game = chess_game_or_404(conn, (data or {}).get("gameId"))
        user_id = session["user_id"]
        if user_id not in {game["white_player_id"], game["black_player_id"]}:
            return
        if game["draw_offer_user_id"] and game["draw_offer_user_id"] != user_id:
            conn.execute(
                "UPDATE chess_games SET status = 'finished', result = %s, draw_offer_user_id = NULL, updated_at = %s WHERE id = %s",
                (json.dumps({"status": "draw_agreed", "winner": None}), now_str(), game["id"]),
            )
        else:
            conn.execute(
                "UPDATE chess_games SET draw_offer_user_id = %s, updated_at = %s WHERE id = %s",
                (user_id, now_str(), game["id"]),
            )
        game = chess_game_or_404(conn, game["id"])
        state = chess_game_state(conn, game, user_id)
        conn.commit()
    emit_safe("game:state_update", state, room=f"chess_{game['id']}")


@socketio.on("game:reconnect")
def chess_socket_reconnect(data):
    if "user_id" not in session:
        return
    with get_db() as conn:
        game = chess_game_or_404(conn, (data or {}).get("gameId"))
        if session["user_id"] not in {game["white_player_id"], game["black_player_id"]}:
            return
        conn.execute(
            "UPDATE chess_games SET disconnected_user_id = NULL, disconnect_deadline_ms = NULL WHERE id = %s",
            (game["id"],),
        )
        game = chess_game_or_404(conn, game["id"])
        state = chess_game_state(conn, game, session["user_id"])
        conn.commit()
    join_room(f"chess_{game['id']}")
    emit_safe("game:state_update", state, room=f"chess_{game['id']}")


@socketio.on("chat:message")
def chess_socket_chat_message(data):
    if "user_id" not in session:
        return
    text = (data or {}).get("text", "").strip()
    if not text or len(text) > 200:
        return
    with get_db() as conn:
        game = chess_game_or_404(conn, (data or {}).get("gameId"))
        user_id = session["user_id"]
        if game["status"] != "active" or user_id not in {
            game["white_player_id"],
            game["black_player_id"],
        }:
            return
        row = conn.execute(
            "INSERT INTO chess_game_chat_messages (game_id, sender_id, text, created_at) VALUES (%s, %s, %s, %s) RETURNING id",
            (game["id"], user_id, text, now_str()),
        ).fetchone()
        user = conn.execute(
            "SELECT display_name, username FROM users WHERE id = %s", (user_id,)
        ).fetchone()
        conn.commit()
    emit_safe(
        "chat:message",
        {
            "id": row["id"],
            "sender_id": user_id,
            "display_name": user["display_name"],
            "username": user["username"],
            "text": text,
        },
        room=f"chess_{game['id']}",
    )


@socketio.on("emote:send")
def chess_socket_emote(data):
    if "user_id" not in session:
        return
    emote = (data or {}).get("emote")
    labels = {
        "respect": "리스펙",
        "goodgame": "좋은 경기",
        "crown": "잘했어요",
        "taunt": "도발",
        "smirk": "도발",
        "laugh": "도발",
        "cry": "눈물",
    }
    emojis = {
        "respect": "👏",
        "goodgame": "🤝",
        "crown": "👑",
        "taunt": "😈",
        "smirk": "😏",
        "laugh": "😂",
        "cry": "😭",
    }
    if emote not in emojis:
        return
    with get_db() as conn:
        game = chess_game_or_404(conn, (data or {}).get("gameId"))
        user_id = session["user_id"]
        if game["status"] != "active" or user_id not in {
            game["white_player_id"],
            game["black_player_id"],
        }:
            return
        user = conn.execute(
            "SELECT display_name, username FROM users WHERE id = %s", (user_id,)
        ).fetchone()
    emit_safe(
        "emote:receive",
        {
            "emoji": emojis[emote],
            "label": labels[emote],
            "sender": user["display_name"] or user["username"],
        },
        room=f"chess_{game['id']}",
    )


@socketio.on("room:leave")
def chess_socket_leave(data):
    # 실제 연결 종료 처리도 아래 disconnect 훅에서 동일하게 판정한다.
    return


chat_bp = create_chat_blueprint({endpoint: globals()[endpoint] for _, _, endpoint in CHAT_ROUTES})
app.register_blueprint(chat_bp)
admin_bp = create_admin_blueprint(
    {endpoint: globals()[endpoint] for _, _, endpoint in ADMIN_ROUTES}
)
app.register_blueprint(admin_bp)


# 서버 실행 시 DB 테이블 자동 생성
try:
    init_db()
except Exception as e:
    app.logger.warning("초기 DB 생성 실패 (서버 연결 대기 중일 수 있음): %s", e)

socketio.start_background_task(cleanup_rate_limit_buckets)
socketio.start_background_task(cleanup_stale_db_rows)


if __name__ == "__main__":
    socketio.run(app, debug=True)

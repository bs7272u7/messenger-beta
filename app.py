from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from flask_socketio import SocketIO, join_room
import json
import os
import base64
import uuid
import re
import random
import time
from threading import Lock
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
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import psycopg2.pool

load_dotenv()
resend.api_key = os.environ.get("RESEND_API_KEY")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 요청 본문 최대 50MB
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-this-in-production")

# threading 모드 & 외부 접근/웹소켓 허용
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# 이미지/동영상이 저장될 폴더와 기본 프로필 사진 경로
UPLOAD_DIR = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
DEFAULT_PROFILE_IMAGE = "/static/default_profile.png"
CLOUDINARY_ENABLED = all(os.environ.get(name) for name in (
    "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"
))
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "bs7272u7/messenger-beta")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
UPDATE_HISTORY_CACHE_SECONDS = 600
_update_history_cache = {"expires_at": 0, "data": None}
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL")
SUPPORT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
SUPPORT_ATTACHMENT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "webm", "mov"}
active_socket_ids = {}
active_socket_ids_lock = Lock()

if CLOUDINARY_ENABLED:
    cloudinary.config(
        cloud_name=os.environ["CLOUDINARY_CLOUD_NAME"],
        api_key=os.environ["CLOUDINARY_API_KEY"],
        api_secret=os.environ["CLOUDINARY_API_SECRET"],
        secure=True,
    )


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
            if key in {"og:title", "og:description", "og:image", "twitter:title", "twitter:description", "twitter:image"} and content:
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
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
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
        content = response.raw.read(512 * 1024, decode_content=True).decode(response.encoding or "utf-8", errors="replace")
        parser = OpenGraphParser()
        parser.feed(content)
        parsed = urlparse(current_url)
        title = parser.metadata.get("og:title") or parser.metadata.get("twitter:title") or parser.title.strip() or parsed.hostname
        description = parser.metadata.get("og:description") or parser.metadata.get("twitter:description") or ""
        image = parser.metadata.get("og:image") or parser.metadata.get("twitter:image") or ""
        if image and urlparse(image).scheme not in {"http", "https"}:
            image = ""
        return {"url": url, "domain": parsed.hostname, "title": title[:200], "description": description[:300], "image": image}
    except (requests.RequestException, OSError, ValueError):
        return None


def get_update_history():
    """최근 GitHub 커밋을 사용자에게 보여줄 업데이트 내역으로 변환한다.

    재현님이 한국어 커밋 메시지를 작성하면 그 문장이 그대로 사용자 화면에 표시된다.
    GitHub API를 매번 호출하지 않도록 10분 동안만 메모리에 보관한다.
    """
    if _update_history_cache["data"] and time.time() < _update_history_cache["expires_at"]:
        return _update_history_cache["data"]

    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        response = requests.get(
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/commits",
            params={"per_page": 5},
            headers=headers,
            timeout=5,
        )
        response.raise_for_status()
        updates = []
        one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        for commit in response.json():
            committed_at = commit["commit"]["author"]["date"]
            date = datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
            if date < one_week_ago:
                continue
            updates.append({
                "version": commit["sha"][:7],
                "date": date.astimezone(timezone(timedelta(hours=9))).strftime("%Y.%m.%d"),
                "message": commit["commit"]["message"].splitlines()[0][:160],
            })

        result = {"updates": updates, "latest_version": updates[0]["version"] if updates else ""}
        _update_history_cache.update({"expires_at": time.time() + UPDATE_HISTORY_CACHE_SECONDS, "data": result})
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
DB_PASSWORD = os.environ.get("DB_PASSWORD", "re_Rxxxxx")
DB_NAME = os.environ.get("DB_NAME", "messenger-beta")
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require" if DATABASE_URL else "prefer")


# ----------------------------------------------------------------
# Database Connection Pool 초기화
# ----------------------------------------------------------------
try:
    if DATABASE_URL:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=20, dsn=DATABASE_URL, sslmode=DB_SSLMODE
        )
    else:
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1, maxconn=20, host=DB_HOST, user=DB_USER,
            password=DB_PASSWORD, dbname=DB_NAME, port=DB_PORT, sslmode=DB_SSLMODE
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

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def commit(self):
        self.raw_conn.commit()

    def close(self):
        self._cursor.close()
        # 커넥션을 닫지 않고 풀(Pool)에 반납합니다.
        if self.pool_obj:
            self.pool_obj.putconn(self.raw_conn)
        else:
            self.raw_conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            try:
                self.raw_conn.rollback()
            except Exception:
                pass
        self.close()


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
                host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
                dbname=DB_NAME, port=DB_PORT, sslmode=DB_SSLMODE
            )
        raw_conn.autocommit = False
        return PGConn(raw_conn)


# ----------------------------------------------------------------
# 헬퍼 함수
# ----------------------------------------------------------------

def get_membership(conn, conversation_id, user_id):
    return conn.execute(
        "SELECT * FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
        (conversation_id, user_id)
    ).fetchone()


def get_owned_message(conn, user_id, message_id):
    return conn.execute("""
        SELECT messages.* FROM messages
        JOIN conversation_members
          ON conversation_members.conversation_id = messages.conversation_id
        WHERE messages.id = %s AND conversation_members.user_id = %s
    """, (message_id, user_id)).fetchone()


def now_str():
    # Render 서버 환경을 대비해 한국 시간(KST, UTC+9)으로 고정
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")


def get_peer_id(conn, conversation_id, user_id):
    conv = conn.execute("SELECT is_group FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
    if not conv or conv["is_group"]:
        return None
    row = conn.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = %s AND user_id != %s",
        (conversation_id, user_id)
    ).fetchone()
    return row["user_id"] if row else None


def is_blocked_either_way(conn, user_a, user_b):
    row = conn.execute(
        "SELECT 1 FROM blocks WHERE (blocker_id = %s AND blocked_id = %s) OR (blocker_id = %s AND blocked_id = %s)",
        (user_a, user_b, user_b, user_a)
    ).fetchone()
    return row is not None


@socketio.on("connect")
def handle_socket_connect():
    if "user_id" not in session:
        return False
    user_id = session["user_id"]
    with active_socket_ids_lock:
        active_socket_ids.setdefault(user_id, set()).add(request.sid)
    join_room(f"user_{user_id}")
    socketio.emit("presence_updated", {"userId": user_id, "online": True})


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
    socketio.emit("presence_updated", {"userId": user_id, "online": False})


def is_user_online(user_id):
    # 한 사용자가 여러 탭을 열어도 마지막 탭까지 닫혀야 오프라인으로 바뀐다.
    with active_socket_ids_lock:
        return bool(active_socket_ids.get(user_id))


def get_conversation_member_ids(conn, conversation_id):
    rows = conn.execute(
        "SELECT user_id FROM conversation_members WHERE conversation_id = %s",
        (conversation_id,)
    ).fetchall()
    return [row["user_id"] for row in rows]


def broadcast_to_conversation(conn, conversation_id, event, payload):
    # 메시지 수정·삭제처럼 대화방 전체가 알아야 하는 일은 참여자별 Socket.IO 방으로 보낸다.
    for uid in get_conversation_member_ids(conn, conversation_id):
        socketio.emit(event, payload, room=f"user_{uid}")


def unhide_conversation(conn, conversation_id):
    conn.execute(
        "UPDATE conversation_members SET hidden_at = NULL WHERE conversation_id = %s",
        (conversation_id,)
    )


def notify_user(user_id, event, payload):
    socketio.emit(event, payload, room=f"user_{user_id}")


def save_base64_image(data_url):
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

        header, encoded = data_url.split(",", 1)
        mime = header.split(";")[0].split(":")[1]
        ext = mime.split("/")[1] if "/" in mime else "png"
        if ext == "jpeg":
            ext = "jpg"
        ext = ext.split(";")[0].strip()

        filename = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)

        with open(filepath, "wb") as f:
            f.write(base64.b64decode(encoded))

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


def init_db():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL
            )
        """)

        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS email_verification_codes (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_codes (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                code TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_image TEXT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                is_group BOOLEAN NOT NULL DEFAULT FALSE,
                name TEXT,
                owner_id INT,
                profile_image TEXT,
                last_activity_id INT NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        cur.execute("""
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
        """)

        cur.execute("""
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
                FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        cur.execute("""
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
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                id SERIAL PRIMARY KEY,
                blocker_id INT NOT NULL,
                blocked_id INT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (blocker_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (blocked_id) REFERENCES users (id) ON DELETE CASCADE,
                UNIQUE (blocker_id, blocked_id)
            )
        """)

        for stmt in [
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_id INT",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS profile_image TEXT",
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_activity_id INT NOT NULL DEFAULT 0",
            "ALTER TABLE conversation_members ADD COLUMN IF NOT EXISTS hidden_at TEXT",
            "ALTER TABLE conversation_members ADD COLUMN IF NOT EXISTS chat_theme VARCHAR(20) NOT NULL DEFAULT 'default'",
            "ALTER TABLE messages ADD COLUMN IF NOT EXISTS video TEXT",
        ]:
            cur.execute(stmt)

        cur.execute("""
            UPDATE conversations
            SET last_activity_id = COALESCE(
                (SELECT MAX(id) FROM messages WHERE messages.conversation_id = conversations.id),
                0
            )
            WHERE last_activity_id = 0
        """)

        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_conv_members_user ON conversation_members(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_friend_requests_addressee ON friend_requests(addressee_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_blocks_blocker ON blocks(blocker_id)",
            "CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks(blocked_id)",
        ]:
            cur.execute(stmt)

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
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)
    return wrapped


def login_required_api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "error": "로그인이 필요합니다."}), 401
        return view(*args, **kwargs)
    return wrapped


# ----------------------------------------------------------------
# 페이지 라우트
# ----------------------------------------------------------------

@app.route("/")
@login_required_page
def home():
    user_id = session["user_id"]
    with get_db() as conn:
        user = conn.execute(
            "SELECT username, display_name, profile_image, email FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()

    if not user:
        session.clear()
        return redirect(url_for("login_page"))

    display_name = user["display_name"] or user ["username"]
    profile_image = user["profile_image"]

    session["display_name"] = display_name
    session["profile_image"] = profile_image

    return render_template(
        "index.html",
        user_id=user_id,
        username=display_name,
        profile_image=profile_image,
        user_email=user["email"],  

    )


@app.route("/login")
def login_page():
    if "user_id" in session:
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/api/logout", methods=["POST"])
@login_required_api
def api_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/support-inquiries", methods=["POST"])
@login_required_api
def send_support_inquiry():
    # 문의는 이메일로 전송되므로 서버에서도 길이·파일 형식·용량을 반드시 다시 검사한다.
    # 브라우저 검사만 믿으면 요청을 직접 조작해 제한을 우회할 수 있다.
    message = (request.form.get("message") or "").strip()
    if len(message) < 10:
        return jsonify({"success": False, "error": "문의 내용은 10자 이상 입력해주세요."}), 400
    if len(message) > 3000:
        return jsonify({"success": False, "error": "문의 내용은 3,000자 이하로 입력해주세요."}), 400
    if not SUPPORT_EMAIL:
        app.logger.error("SUPPORT_EMAIL 환경변수가 설정되지 않았습니다.")
        return jsonify({"success": False, "error": "문의 수신 이메일이 아직 설정되지 않았습니다."}), 503

    attachment = request.files.get("attachment")
    attachment_data = None
    if attachment and attachment.filename:
        extension = attachment.filename.rsplit(".", 1)[-1].lower() if "." in attachment.filename else ""
        if extension not in SUPPORT_ATTACHMENT_EXTENSIONS:
            return jsonify({"success": False, "error": "사진(png, jpg, gif, webp) 또는 동영상(mp4, webm, mov)만 첨부할 수 있습니다."}), 400

        file_content = attachment.read(SUPPORT_ATTACHMENT_MAX_BYTES + 1)
        if len(file_content) > SUPPORT_ATTACHMENT_MAX_BYTES:
            return jsonify({"success": False, "error": "첨부파일은 10MB 이하만 보낼 수 있습니다."}), 400

        safe_filename = re.sub(r"[^\w.가-힣-]", "_", attachment.filename)
        attachment_data = {
            "filename": safe_filename or f"attachment.{extension}",
            "content": base64.b64encode(file_content).decode("ascii"),
        }

    user_id = session["user_id"]
    with get_db() as conn:
        user = conn.execute(
            "SELECT username, display_name, email FROM users WHERE id = %s", (user_id,)
        ).fetchone()

    if not user:
        session.clear()
        return jsonify({"success": False, "error": "로그인 정보를 확인할 수 없습니다."}), 401

    now = time.time()
    # 문의 메일 발송 기능이 스팸 발송 통로가 되지 않도록 계정별 전송 간격을 둔다.
    if now - session.get("last_support_inquiry_at", 0) < 60:
        return jsonify({"success": False, "error": "문의는 1분에 한 번만 보낼 수 있습니다."}), 429

    display_name = user["display_name"] or user["username"]
    email_params = {
        "from": get_resend_sender(),
        "to": [SUPPORT_EMAIL],
        "subject": f"[클라우드 채팅 문의] {display_name}",
        "html": (
            "<h2>새 문의사항</h2>"
            f"<p><strong>이름:</strong> {escape(display_name)}</p>"
            f"<p><strong>아이디:</strong> {escape(user['username'])}</p>"
            f"<p><strong>이메일:</strong> {escape(user['email'] or '등록된 이메일 없음')}</p>"
            f"<hr><p>{escape(message).replace(chr(10), '<br>')}</p>"
        ),
    }
    if user["email"]:
        email_params["reply_to"] = user["email"]
    if attachment_data:
        email_params["attachments"] = [attachment_data]

    try:
        resend.Emails.send(email_params)
        session["last_support_inquiry_at"] = now
    except Exception:
        app.logger.exception("문의사항 이메일 발송 실패")
        return jsonify({"success": False, "error": "문의 전송에 실패했습니다. 잠시 후 다시 시도해주세요."}), 500

    return jsonify({"success": True, "message": "문의가 전송되었습니다. 확인 후 답변드리겠습니다."})


@app.route("/api/updates", methods=["GET"])
@login_required_api
def get_updates():
    update_history = get_update_history()
    if update_history is None:
        return jsonify({"success": False, "error": "업데이트 내역을 불러오지 못했습니다."}), 503
    return jsonify({"success": True, **update_history})


# ----------------------------------------------------------------
# 인증 API
# ----------------------------------------------------------------

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    password = data.get("password") or ""
    display_name = (data.get("display_name") or "").strip()
    username = (data.get("username") or "").strip().lower()
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    if not username or not email or not password:
        return jsonify({"success": False, "error": "아이디, 이메일, 비밀번호를 입력해주세요."})
    if not re.fullmatch(r"[a-z0-9]{5,}", username):
        return jsonify({"success": False, "error": "아이디는 영문 소문자와 숫자로 5자 이상 입력해주세요."})
    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."})
    if not re.fullmatch(r"(?=.*[a-z])(?=.*[0-9])(?=.*[^a-zA-Z0-9]).{7,}", password):
        return jsonify({"success": False, "error": "비밀번호는 영어 소문자, 숫자, 특수문자를 모두 포함해 7자 이상이어야 합니다."})

    with get_db() as conn:
        verification = conn.execute(
            "SELECT * FROM email_verification_codes WHERE email = %s AND code = %s",
            (email, code)
        ).fetchone()
        if not verification:
            return jsonify({"success": False, "error": "인증번호가 올바르지 않습니다."})
        if verification["expires_at"] < now_str():
            return jsonify({"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."})

        existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            return jsonify({"success": False, "error": "이미 가입된 이메일입니다."})

        existing_username = conn.execute("SELECT id FROM users WHERE username = %s", (username,)).fetchone()
        if existing_username:
            return jsonify({"success": False, "error": "이미 사용 중인 아이디입니다."})

        display_name = display_name or username

        row = conn.execute(
            "INSERT INTO users (username, password_hash, display_name, profile_image, email) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (username, generate_password_hash(password), display_name, DEFAULT_PROFILE_IMAGE, email)
        ).fetchone()

        user_id = row["id"]
        session["profile_image"] = DEFAULT_PROFILE_IMAGE

        conn.execute("DELETE FROM email_verification_codes WHERE email = %s", (email,))
        conn.commit()

    session["user_id"] = user_id
    session["username"] = username
    session["display_name"] = display_name
    return jsonify({"success": True})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    identifier = (data.get("identifier") or "").strip()
    password = data.get("password") or ""

    with get_db() as conn:
        if "@" in identifier:
            user = conn.execute(
                "SELECT id, username, password_hash, display_name, profile_image FROM users WHERE email = %s",
                (identifier.lower(),)
            ).fetchone()
        else:
            user = conn.execute(
                "SELECT id, username, password_hash, display_name, profile_image FROM users WHERE username = %s",
                (identifier,)
            ).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"success": False, "error": "아이디/이메일 또는 비밀번호가 올바르지 않습니다."})

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user["display_name"] or user["username"]
    session["profile_image"] = user["profile_image"]
    return jsonify({"success": True})


# ----------------------------------------------------------------
# 친구 요청 API
# ----------------------------------------------------------------

@app.route("/api/friend-requests", methods=["POST"])
@login_required_api
def send_friend_request():
    user_id = session["user_id"]
    data = request.get_json() or {}
    target_username = (data.get("username") or "").strip()

    if not target_username:
        return jsonify({"success": False, "error": "아이디를 입력해주세요."})
    if target_username == session.get("username"):
        return jsonify({"success": False, "error": "자기 자신에게는 요청할 수 없습니다."})

    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE username = %s", (target_username,)).fetchone()
        if not target:
            return jsonify({"success": False, "error": "존재하지 않는 아이디입니다."})
        target_id = target["id"]

        if is_blocked_either_way(conn, user_id, target_id):
            return jsonify({"success": False, "error": "차단 관계에서는 친구 요청을 보낼 수 없습니다."})

        already_friends = conn.execute("""
            SELECT c.id FROM conversations c
            JOIN conversation_members m1 ON m1.conversation_id = c.id AND m1.user_id = %s
            JOIN conversation_members m2 ON m2.conversation_id = c.id AND m2.user_id = %s
            WHERE c.is_group = FALSE
        """, (user_id, target_id)).fetchone()
        if already_friends:
            return jsonify({"success": False, "error": "이미 친구입니다."})

        reverse = conn.execute(
            "SELECT id FROM friend_requests WHERE requester_id = %s AND addressee_id = %s AND status = 'pending'",
            (target_id, user_id)
        ).fetchone()
        if reverse:
            _accept_friend_request(conn, reverse["id"], user_id)
            conn.commit()
            notify_user(target_id, "friend_updated", {})
            return jsonify({"success": True, "autoAccepted": True})

        existing = conn.execute(
            "SELECT id, status FROM friend_requests WHERE requester_id = %s AND addressee_id = %s",
            (user_id, target_id)
        ).fetchone()
        if existing and existing["status"] == "pending":
            return jsonify({"success": False, "error": "이미 요청을 보냈습니다."})

        if existing:
            conn.execute(
                "UPDATE friend_requests SET status = 'pending', created_at = %s WHERE id = %s",
                (now_str(), existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO friend_requests (requester_id, addressee_id, status, created_at) VALUES (%s, %s, 'pending', %s)",
                (user_id, target_id, now_str())
            )
        conn.commit()
        notify_user(target_id, "friend_updated", {})
    return jsonify({"success": True})

@app.route("/api/friend-requests/<int:request_id>", methods=["DELETE"])
@login_required_api
def cancel_friend_request(request_id):
    user_id = session["user_id"]

    with get_db() as conn:
        request_row = conn.execute(
            """
            SELECT id, addressee_id
            FROM friend_requests
            WHERE id = %s
                AND requester_id = %s
                AND status = 'pending'
            """,
            (request_id, user_id)
        ).fetchone()

        if not request_row:
            return jsonify({
                "success": False,
                "error": "취소할 친구 요청을 찾을 수 없습니다."
            }), 404

        conn.execute(
            "DELETE FROM friend_requests WHERE id = %s",
            (request_id)
        )
        conn.commit()

    notify_user(request_row["addressee_id"], "friend_updated", {})
    return jsonify({"success": True})


@app.route("/api/friend-requests", methods=["GET"])
@login_required_api
def list_friend_requests():
    user_id = session["user_id"]
    with get_db() as conn:
        incoming = conn.execute("""
            SELECT friend_requests.id, users.display_name, friend_requests.created_at
            FROM friend_requests
            JOIN users ON users.id = friend_requests.requester_id
            WHERE friend_requests.addressee_id = %s AND friend_requests.status = 'pending'
            ORDER BY friend_requests.created_at DESC
        """, (user_id,)).fetchall()

        outgoing = conn.execute("""
            SELECT friend_requests.id, users.display_name, friend_requests.created_at
            FROM friend_requests
            JOIN users ON users.id = friend_requests.addressee_id
            WHERE friend_requests.requester_id = %s AND friend_requests.status = 'pending'
            ORDER BY friend_requests.created_at DESC
        """, (user_id,)).fetchall()

    return jsonify({
        "incoming": [dict(row) for row in incoming],
        "outgoing": [dict(row) for row in outgoing],
    })


def _accept_friend_request(conn, request_id, acting_user_id):
    req = conn.execute("SELECT * FROM friend_requests WHERE id = %s", (request_id,)).fetchone()
    conn.execute("UPDATE friend_requests SET status = 'accepted' WHERE id = %s", (request_id,))

    conv_row = conn.execute(
        "INSERT INTO conversations (is_group, name, created_at) VALUES (FALSE, NULL, %s) RETURNING id",
        (now_str(),)
    ).fetchone()
    conversation_id = conv_row["id"]
    
    for uid in (req["requester_id"], req["addressee_id"]):
        conn.execute(
            "INSERT INTO conversation_members (conversation_id, user_id, last_read_message_id, joined_at) VALUES (%s, %s, 0, %s)",
            (conversation_id, uid, now_str())
        )
    return conversation_id


@app.route("/api/friend-requests/<int:request_id>/respond", methods=["POST"])
@login_required_api
def respond_friend_request(request_id):
    user_id = session["user_id"]
    data = request.get_json() or {}
    accept = bool(data.get("accept"))

    with get_db() as conn:
        req = conn.execute(
            "SELECT * FROM friend_requests WHERE id = %s AND addressee_id = %s AND status = 'pending'",
            (request_id, user_id)
        ).fetchone()
        if not req:
            return jsonify({"success": False, "error": "요청을 찾을 수 없습니다."}), 404

        if accept:
            _accept_friend_request(conn, request_id, user_id)
        else:
            conn.execute("UPDATE friend_requests SET status = 'declined' WHERE id = %s", (request_id,))
        conn.commit()
        requester_id = req["requester_id"]

    notify_user(requester_id, "friend_updated", {})
    return jsonify({"success": True})


# ----------------------------------------------------------------
# 차단 API
# ----------------------------------------------------------------

@app.route("/api/blocks", methods=["GET"])
@login_required_api
def list_blocks():
    user_id = session["user_id"]
    with get_db() as conn:
        rows = conn.execute("""
            SELECT users.id, users.display_name, users.username
            FROM blocks
            JOIN users ON users.id = blocks.blocked_id
            WHERE blocks.blocker_id = %s
            ORDER BY blocks.created_at DESC
        """, (user_id,)).fetchall()
    return jsonify({"blocked": [dict(row) for row in rows]})


@app.route("/api/blocks", methods=["POST"])
@login_required_api
def block_user():
    user_id = session["user_id"]
    data = request.get_json() or {}
    target_id = data.get("user_id")

    if not target_id:
        return jsonify({"success": False, "error": "차단할 대상을 지정해주세요."}), 400
    if target_id == user_id:
        return jsonify({"success": False, "error": "자기 자신은 차단할 수 없습니다."}), 400

    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id = %s", (target_id,)).fetchone()
        if not target:
            return jsonify({"success": False, "error": "사용자를 찾을 수 없습니다."}), 404

        existing = conn.execute(
            "SELECT id FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
            (user_id, target_id)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (%s, %s, %s)",
                (user_id, target_id, now_str())
            )
            conn.commit()
    notify_user(target_id, "friend_updated", {})
    return jsonify({"success": True})


@app.route("/api/blocks/<int:target_id>", methods=["DELETE"])
@login_required_api
def unblock_user(target_id):
    user_id = session["user_id"]
    with get_db() as conn:
        conn.execute(
            "DELETE FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
            (user_id, target_id)
        )
        conn.commit()
    notify_user(target_id, "friend_updated", {})
    return jsonify({"success": True})


# ----------------------------------------------------------------
# 대화방(conversations) API
# ----------------------------------------------------------------

@app.route("/api/conversations", methods=["GET"])
@login_required_api
def get_conversations():
    user_id = session["user_id"]
    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.is_group, c.name, c.profile_image, c.last_activity_id,
                   cm.last_read_message_id, cm.chat_theme
            FROM conversations c
            JOIN conversation_members cm ON cm.conversation_id = c.id
            WHERE cm.user_id = %s AND cm.hidden_at IS NULL
        """, (user_id,)).fetchall()

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
                peer = conn.execute("""
                    SELECT users.id, users.display_name, users.username, users.profile_image FROM conversation_members
                    JOIN users ON users.id = conversation_members.user_id
                    WHERE conversation_members.conversation_id = %s AND conversation_members.user_id != %s
                """, (conversation_id, user_id)).fetchone()

                if peer:
                    display_name = peer["display_name"] or peer["username"]
                    peer_id = peer["id"]
                    peer_username = peer["username"]
                    peer_profile_image = peer["profile_image"]
                    blocked_by_me = conn.execute(
                        "SELECT 1 FROM blocks WHERE blocker_id = %s AND blocked_id = %s", (user_id, peer_id)
                    ).fetchone() is not None
                    blocked_me = conn.execute(
                        "SELECT 1 FROM blocks WHERE blocker_id = %s AND blocked_id = %s", (peer_id, user_id)
                    ).fetchone() is not None
                else:
                    display_name = "(알 수 없음)"

            last_msg = conn.execute(
                "SELECT id, text, image, video, time FROM messages WHERE conversation_id = %s ORDER BY id DESC LIMIT 1",
                (conversation_id,)
            ).fetchone()

            message_text, last_time = "", ""
            last_msg_id = last_msg["id"] if last_msg else 0
            if last_msg:
                if last_msg["video"]:
                    message_text = "__VIDEO__동영상"
                elif last_msg["image"]:
                    message_text = "__CAMERA__사진"
                else:
                    message_text = last_msg["text"] or ""
                last_time = last_msg["time"] or ""

            member_count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM conversation_members WHERE conversation_id = %s",
                (conversation_id,)
            ).fetchone()
            member_count = member_count_row["cnt"] if member_count_row else 0

            unread_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM messages WHERE conversation_id = %s AND id > %s",
                (conversation_id, row["last_read_message_id"])
            ).fetchone()
            unread = unread_row["cnt"] if unread_row else 0

            result.append({
                "id": conversation_id,
                "isGroup": bool(row["is_group"]),
                "name": display_name,
                "message": message_text,
                "lastTime": last_time,
                "chatTheme": row["chat_theme"] or "default",
                "unreadCount": unread,
                "peerId": peer_id,
                "peerUsername": peer_username,
                "peerProfileImage": peer_profile_image,
                "isOnline": bool(peer_id and is_user_online(peer_id)),
                "groupProfileImage": group_profile_image,
                "memberCount": member_count,
                "blockedByMe": blocked_by_me,
                "blockedMe": blocked_me,
                "_sortKey": row["last_activity_id"] or last_msg_id,
            })
        result.sort(key=lambda r: r["_sortKey"], reverse=True)
        return jsonify(result)


@app.route("/api/conversations", methods=["POST"])
@login_required_api
def create_group_conversation():
    user_id = session["user_id"]
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    usernames = data.get("usernames") or []

    if not name:
        return jsonify({"success": False, "error": "방 이름을 입력해주세요."})

    with get_db() as conn:
        member_ids = {user_id}
        for uname in usernames:
            row = conn.execute("SELECT id FROM users WHERE username = %s", (uname,)).fetchone()
            if not row:
                return jsonify({"success": False, "error": f"'{uname}' 사용자를 찾을 수 없습니다."})
            member_ids.add(row["id"])

        if len(member_ids) < 3:
            return jsonify({"success": False, "error": "그룹 채팅은 3명 이상이어야 합니다."})

        conv_row = conn.execute(
            "INSERT INTO conversations (is_group, name, owner_id, profile_image, created_at) VALUES (TRUE, %s, %s, %s, %s) RETURNING id",
            (name, user_id, DEFAULT_PROFILE_IMAGE, now_str())
        ).fetchone()
        conversation_id = conv_row["id"]
        
        for uid in member_ids:
            conn.execute(
                "INSERT INTO conversation_members (conversation_id, user_id, last_read_message_id, joined_at) VALUES (%s, %s, 0, %s)",
                (conversation_id, uid, now_str())
            )
        conn.commit()
    return jsonify({"success": True, "conversationId": conversation_id})


@app.route("/api/conversations/<int:conversation_id>/theme", methods=["PATCH"])
@login_required_api
def update_conversation_theme(conversation_id):
    """채팅 테마는 같은 대화방이라도 사용자별로 저장한다."""
    theme = (request.get_json() or {}).get("theme", "default")
    if theme not in {"default", "heart", "teddy"}:
        return jsonify({"success": False, "error": "지원하지 않는 채팅 테마입니다."}), 400

    user_id = session["user_id"]
    with get_db() as conn:
        membership = get_membership(conn, conversation_id, user_id)
        if not membership:
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404
        conn.execute(
            "UPDATE conversation_members SET chat_theme = %s WHERE conversation_id = %s AND user_id = %s",
            (theme, conversation_id, user_id),
        )
        conn.commit()
    return jsonify({"success": True, "theme": theme})


@app.route("/api/conversations/<int:conversation_id>/name", methods=["PATCH"])
@login_required_api
def rename_group_conversation(conversation_id):
    user_id = session["user_id"]
    data = request.get_json() or {}
    new_name = (data.get("name") or "").strip()

    if not new_name:
        return jsonify({"success": False, "error": "방 이름을 입력해주세요."})

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conv = conn.execute("SELECT is_group, owner_id FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
        if not conv or not conv["is_group"]:
            return jsonify({"success": False, "error": "그룹 채팅만 이름을 바꿀 수 있습니다."}), 400

        if conv["owner_id"] != user_id:
            return jsonify({"success": False, "error": "방장만 그룹 이름을 바꿀 수 있습니다."}), 403

        conn.execute("UPDATE conversations SET name = %s WHERE id = %s", (new_name, conversation_id))
        conn.commit()
        broadcast_to_conversation(conn, conversation_id, "conversation_updated", {"conversationId": conversation_id})

    return jsonify({"success": True, "name": new_name})


@app.route("/api/conversations/<int:conversation_id>/leave", methods=["DELETE"])
@login_required_api
def leave_conversation(conversation_id):
    user_id = session["user_id"]
    with get_db() as conn:
        membership = get_membership(conn, conversation_id, user_id)
        if not membership:
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conn.execute(
            "DELETE FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
            (conversation_id, user_id)
        )

        conv = conn.execute("SELECT owner_id, is_group FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
        if conv and conv["is_group"] and conv["owner_id"] == user_id:
            new_owner = conn.execute(
                "SELECT user_id FROM conversation_members WHERE conversation_id = %s ORDER BY joined_at ASC LIMIT 1",
                (conversation_id,)
            ).fetchone()
            if new_owner:
                conn.execute("UPDATE conversations SET owner_id = %s WHERE id = %s", (new_owner["user_id"], conversation_id))

        remaining_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM conversation_members WHERE conversation_id = %s", (conversation_id,)
        ).fetchone()
        remaining = remaining_row["cnt"] if remaining_row else 0

        if remaining == 0:
            image_rows = conn.execute(
                "SELECT image FROM messages WHERE conversation_id = %s AND image IS NOT NULL", (conversation_id,)
            ).fetchall()
            conn.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            conn.commit()
            for row in image_rows:
                delete_image_file(row["image"])
            return jsonify({"success": True})

        conn.commit()
    return jsonify({"success": True})


@app.route("/api/conversations/<int:conversation_id>/hide", methods=["POST"])
@login_required_api
def hide_conversation(conversation_id):
    user_id = session["user_id"]
    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conn.execute(
            "UPDATE conversation_members SET hidden_at = %s WHERE conversation_id = %s AND user_id = %s",
            (now_str(), conversation_id, user_id)
        )
        conn.commit()
    return jsonify({"success": True})


@app.route("/api/conversations/<int:conversation_id>/members", methods=["GET"])
@login_required_api
def get_conversation_members(conversation_id):
    user_id = session["user_id"]
    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conv = conn.execute("SELECT owner_id, profile_image FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
        owner_id = conv["owner_id"] if conv else None
        group_profile_image = conv["profile_image"] if conv else None

        rows = conn.execute("""
            SELECT users.id, users.username, users.display_name, users.profile_image
            FROM conversation_members
            JOIN users ON users.id = conversation_members.user_id
            WHERE conversation_members.conversation_id = %s
        """, (conversation_id,)).fetchall()

        members = [{
            "id": row["id"],
            "username": row["username"],
            "name": row["display_name"] or row["username"],
            "profileImage": row["profile_image"],
        } for row in rows]

    return jsonify({
        "success": True,
        "members": members,
        "ownerId": owner_id,
        "groupProfileImage": group_profile_image,
    })


@app.route("/api/conversations/<int:conversation_id>/members", methods=["POST"])
@login_required_api
def invite_conversation_members(conversation_id):
    user_id = session["user_id"]
    data = request.get_json() or {}
    usernames = data.get("usernames") or []

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conv = conn.execute("SELECT is_group FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
        if not conv or not conv["is_group"]:
            return jsonify({"success": False, "error": "그룹 채팅에서만 멤버를 초대할 수 있습니다."}), 400

        for uname in usernames:
            row = conn.execute("SELECT id FROM users WHERE username = %s", (uname,)).fetchone()
            if not row:
                return jsonify({"success": False, "error": f"'{uname}' 사용자를 찾을 수 없습니다."})

            if get_membership(conn, conversation_id, row["id"]):
                continue

            conn.execute(
                "INSERT INTO conversation_members (conversation_id, user_id, last_read_message_id, joined_at) VALUES (%s, %s, 0, %s)",
                (conversation_id, row["id"], now_str())
            )

        conn.commit()
        broadcast_to_conversation(conn, conversation_id, "friend_updated", {})

    return jsonify({"success": True})


@app.route("/api/conversations/<int:conversation_id>/members/<int:member_user_id>", methods=["DELETE"])
@login_required_api
def remove_conversation_member(conversation_id, member_user_id):
    user_id = session["user_id"]
    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conv = conn.execute("SELECT is_group, owner_id FROM conversations WHERE id = %s", (conversation_id,)).fetchone()
        if not conv or not conv["is_group"]:
            return jsonify({"success": False, "error": "그룹 채팅에서만 멤버를 내보낼 수 있습니다."}), 400

        if conv["owner_id"] != user_id:
            return jsonify({"success": False, "error": "방장만 멤버를 내보낼 수 있습니다."}), 403

        if member_user_id == user_id:
            return jsonify({"success": False, "error": "본인은 내보낼 수 없습니다. 나가기 기능을 이용해주세요."}), 400

        if not get_membership(conn, conversation_id, member_user_id):
            return jsonify({"success": False, "error": "해당 멤버를 찾을 수 없습니다."}), 404

        conn.execute(
            "DELETE FROM conversation_members WHERE conversation_id = %s AND user_id = %s",
            (conversation_id, member_user_id)
        )
        conn.commit()

        notify_user(member_user_id, "friend_updated", {})
        broadcast_to_conversation(conn, conversation_id, "conversation_updated", {"conversationId": conversation_id})

    return jsonify({"success": True})


# ----------------------------------------------------------------
# 메시지 API
# ----------------------------------------------------------------

@app.route("/api/link-preview", methods=["POST"])
@login_required_api
def link_preview():
    url = (request.get_json() or {}).get("url", "").strip()
    preview = get_link_preview(url)
    return jsonify({"success": bool(preview), "preview": preview})

@app.route("/api/conversations/<int:conversation_id>/messages", methods=["GET"])
@login_required_api
def get_messages(conversation_id):
    user_id = session["user_id"]
    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        conv = conn.execute("SELECT is_group FROM conversations WHERE id = %s", (conversation_id,)).fetchone()

        member_read_rows = conn.execute(
            "SELECT user_id, last_read_message_id FROM conversation_members WHERE conversation_id = %s",
            (conversation_id,)
        ).fetchall()
        member_last_read = {m["user_id"]: m["last_read_message_id"] for m in member_read_rows}

        sender_names = {}
        sender_images = {}
        if conv and conv["is_group"]:
            member_rows = conn.execute("""
                SELECT users.id, users.display_name, users.username, users.profile_image FROM conversation_members
                JOIN users ON users.id = conversation_members.user_id
                WHERE conversation_members.conversation_id = %s       
            """, (conversation_id,)).fetchall()
            sender_names = {m["id"]: (m["display_name"] or m["username"]) for m in member_rows}
            sender_images = {m["id"]: m["profile_image"] for m in member_rows}

        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = %s ORDER BY id ASC", (conversation_id,)
        ).fetchall()

        messages = []
        for row in rows:
            unread_count = sum(
                1 for uid, last_read in member_last_read.items()
                if uid != row["sender_id"] and last_read < row["id"]
            )
            messages.append({
                "id": row["id"],
                "senderId": row["sender_id"],
                "senderName": sender_names.get(row["sender_id"]),
                "senderProfileImage": sender_images.get(row["sender_id"]),
                "mine": row["sender_id"] == user_id, 
                "text": row["text"],
                "image": row["image"],
                "video": row["video"],
                "time": row["time"],
                "date": row["date"],
                "reply": json.loads(row["reply"]) if row["reply"] else None,
                "edited": bool(row["edited"]),
                "pinned": bool(row["pinned"]),
                "reactions": json.loads(row["reactions"]) if row["reactions"] else [],
                "unreadCount": unread_count,
            })
        return jsonify(messages)


@app.route("/api/conversations/<int:conversation_id>/messages", methods=["POST"])
@login_required_api
def send_message(conversation_id):
    user_id = session["user_id"]
    data = request.get_json() or {}
    reply = data.get("reply")

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return jsonify({"success": False, "error": "차단된 사용자와는 메시지를 주고받을 수 없습니다."}), 403

        msg_row = conn.execute("""
            INSERT INTO messages (conversation_id, sender_id, text, image, time, date, reply, edited, pinned, reactions)
            VALUES (%s, %s, %s, NULL, %s, %s, %s, FALSE, FALSE, %s) RETURNING id
        """, (
            conversation_id,
            user_id,
            data.get("text"),
            data.get("time"),
            data.get("date"),
            json.dumps(reply) if reply else None,
            json.dumps([])
        )).fetchone()
        new_message_id = msg_row["id"]

        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            (new_message_id, conversation_id, user_id)
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id)
        )

        unhide_conversation(conn, conversation_id)

        conn.commit()
        broadcast_to_conversation(conn, conversation_id, "conversation_updated", {"conversationId": conversation_id})
        return jsonify({"success": True})


@app.route("/api/conversations/<int:conversation_id>/messages/image", methods=["POST"])
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

        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return jsonify({"success": False, "error": "차단된 사용자와는 메시지를 주고받을 수 없습니다."}), 403

        msg_row = conn.execute("""
            INSERT INTO messages (conversation_id, sender_id, text, image, time, date, reply, edited, pinned, reactions)
            VALUES (%s, %s, NULL, %s, %s, %s, NULL, FALSE, FALSE, %s) RETURNING id
        """, (
            conversation_id,
            user_id,
            image_path,
            data.get("time"),
            data.get("date"),
            json.dumps([])
        )).fetchone()
        new_message_id = msg_row["id"]

        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            (new_message_id, conversation_id, user_id)
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id)
        )

        unhide_conversation(conn, conversation_id)

        conn.commit()
        broadcast_to_conversation(conn, conversation_id, "conversation_updated", {"conversationId": conversation_id})
    return jsonify({"success": True, "image": image_path})


ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "mov"}

def is_allowed_video(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS


@app.route("/api/conversations/<int:conversation_id>/messages/video", methods=["POST"])
@login_required_api
def send_video(conversation_id):
    user_id = session["user_id"]

    video_file = request.files.get("video")
    if not video_file or video_file.filename == "":
        return jsonify({"success": False, "error": "동영상 파일이 없습니다."}), 400

    if not is_allowed_video(video_file.filename):
        return jsonify({"success": False, "error": "지원하지 않는 동영상 형식입니다 (mp4, webm, mov만 가능)."}), 400

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        peer_id = get_peer_id(conn, conversation_id, user_id)
        if peer_id and is_blocked_either_way(conn, user_id, peer_id):
            return jsonify({"success": False, "error": "차단된 사용자와는 메시지를 주고받을 수 없습니다."}), 403

        ext = video_file.filename.rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        video_file.save(os.path.join(UPLOAD_DIR, filename))
        video_path = f"/static/uploads/{filename}"

        msg_row = conn.execute("""
            INSERT INTO messages (conversation_id, sender_id, text, image, video, time, date, reply, edited, pinned, reactions)
            VALUES (%s, %s, NULL, NULL, %s, %s, %s, NULL, FALSE, FALSE, %s) RETURNING id
        """, (
            conversation_id,
            user_id,
            video_path,
            request.form.get("time"),
            request.form.get("date"),
            json.dumps([])
        )).fetchone()
        new_message_id = msg_row["id"]

        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            (new_message_id, conversation_id, user_id)
        )
        conn.execute(
            "UPDATE conversations SET last_activity_id = %s WHERE id = %s",
            (new_message_id, conversation_id)
        )

        unhide_conversation(conn, conversation_id)

        conn.commit()
        broadcast_to_conversation(conn, conversation_id, "conversation_updated", {"conversationId": conversation_id})
    return jsonify({"success": True, "video": video_path})


@app.route("/api/messages/<int:message_id>", methods=["PATCH"])
@login_required_api
def edit_message(message_id):
    user_id = session["user_id"]
    data = request.get_json() or {}

    with get_db() as conn:
        msg = get_owned_message(conn, user_id, message_id)
        if msg is None:
            return jsonify({"success": False, "error": "메시지를 찾을 수 없습니다."}), 404
        if msg["sender_id"] != user_id:
            return jsonify({"success": False, "error": "본인 메시지만 수정할 수 있습니다."}), 403

        conn.execute(
            "UPDATE messages SET text = %s, edited = TRUE WHERE id = %s",
            (data.get("text"), message_id)
        )
        conn.commit()
        broadcast_to_conversation(conn, msg["conversation_id"], "conversation_updated", {"conversationId": msg["conversation_id"]})
    return jsonify({"success": True})


@app.route("/api/messages/<int:message_id>", methods=["DELETE"])
@login_required_api
def delete_message(message_id):
    user_id = session["user_id"]

    with get_db() as conn:
        msg = get_owned_message(conn, user_id, message_id)
        if msg is None:
            return jsonify({"success": False, "error": "메시지를 찾을 수 없습니다."}), 404
        if msg["sender_id"] != user_id:
            return jsonify({"success": False, "error": "본인 메시지만 삭제할 수 있습니다."}), 403

        conn.execute("DELETE FROM messages WHERE id = %s", (message_id,))
        conn.commit()
        broadcast_to_conversation(conn, msg["conversation_id"], "conversation_updated", {"conversationId": msg["conversation_id"]})

    delete_image_file(msg["image"])
    return jsonify({"success": True})


@app.route("/api/messages/<int:message_id>/pin", methods=["POST"])
@login_required_api
def pin_message(message_id):
    user_id = session["user_id"]

    with get_db() as conn:
        msg = get_owned_message(conn, user_id, message_id)
        if msg is None:
            return jsonify({"success": False, "error": "메시지를 찾을 수 없습니다."}), 404

        now_pinned = not bool(msg["pinned"])
        conn.execute("UPDATE messages SET pinned = FALSE WHERE conversation_id = %s", (msg["conversation_id"],))
        if now_pinned:
            conn.execute("UPDATE messages SET pinned = TRUE WHERE id = %s", (message_id,))
        conn.commit()
        broadcast_to_conversation(conn, msg["conversation_id"], "conversation_updated", {"conversationId": msg["conversation_id"]})
    return jsonify({"success": True})


@app.route("/api/messages/<int:message_id>/react", methods=["POST"])
@login_required_api
def react_message(message_id):
    user_id = session["user_id"]
    data = request.get_json() or {}
    emoji = data.get("emoji")

    with get_db() as conn:
        msg = get_owned_message(conn, user_id, message_id)
        if msg is None:
            return jsonify({"success": False, "error": "메시지를 찾을 수 없습니다."}), 404

        reactions = json.loads(msg["reactions"]) if msg["reactions"] else []

        if emoji in reactions:
            reactions.remove(emoji)
        else:
            reactions.append(emoji)

        conn.execute("UPDATE messages SET reactions = %s WHERE id = %s", (json.dumps(reactions), message_id))
        conn.commit()
        broadcast_to_conversation(conn, msg["conversation_id"], "conversation_updated", {"conversationId": msg["conversation_id"]})
    return jsonify({"success": True, "reactions": reactions})


@app.route("/api/account/display-name", methods=["PATCH"])
@login_required_api
def update_display_name():
    user_id = session["user_id"]
    data = request.get_json() or {}
    display_name = (data.get("display_name") or "").strip()

    if not display_name:
        return jsonify({"success": False, "error": "이름을 입력해주세요."})

    with get_db() as conn:
        conn.execute("UPDATE users SET display_name = %s WHERE id = %s", (display_name, user_id))
        conn.commit()

    session["display_name"] = display_name
    return jsonify({"success": True, "display_name": display_name})


@app.route("/api/account/username", methods=["PATCH"])
@login_required_api
def update_username():
    user_id = session["user_id"]
    data = request.get_json() or {}
    new_username = (data.get("new_username") or "").strip()
    current_password = data.get("current_password") or ""

    if not re.fullmatch(r"[a-z0-9]{5,}", new_username):
        return jsonify({"success": False, "error": "아이디는 영어 소문자와 숫자 조합으로 5자 이상이어야 합니다."})

    with get_db() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"success": False, "error": "현재 비밀번호가 일치하지 않습니다."})

        existing = conn.execute("SELECT id FROM users WHERE username = %s AND id != %s", (new_username, user_id)).fetchone()
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

    if not re.fullmatch(r"(?=.*[a-z])(?=.*[0-9])(?=.*[^a-zA-Z0-9]).{7,}", new_password):
        return jsonify({"success": False, "error": "비밀번호는 영어 소문자, 숫자, 특수문자를 모두 포함해 7자 이상이어야 합니다."})

    with get_db() as conn:
        user = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,)).fetchone()
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"success": False, "error": "현재 비밀번호가 일치하지 않습니다."})

        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (generate_password_hash(new_password), user_id)
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
        conn.commit()

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
        conn.execute("UPDATE users SET profile_image = %s WHERE id = %s", (DEFAULT_PROFILE_IMAGE, user_id))
        conn.commit()

    if user and user["profile_image"] and user["profile_image"] != DEFAULT_PROFILE_IMAGE:
        delete_image_file(user["profile_image"])

    session["profile_image"] = DEFAULT_PROFILE_IMAGE
    return jsonify({"success": True, "profile_image": DEFAULT_PROFILE_IMAGE})


@app.route("/api/conversations/<int:conversation_id>/photo", methods=["PATCH"])
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
            "SELECT is_group, owner_id, profile_image FROM conversations WHERE id = %s", (conversation_id,)
        ).fetchone()
        if not conv or not conv["is_group"]:
            return jsonify({"success": False, "error": "그룹 채팅만 사진을 바꿀 수 있습니다."}), 400
        if conv["owner_id"] != user_id:
            return jsonify({"success": False, "error": "방장만 그룹 사진을 바꿀 수 있습니다."}), 403

        old_image = conv["profile_image"]
        conn.execute("UPDATE conversations SET profile_image = %s WHERE id = %s", (new_path, conversation_id))
        conn.commit()
        broadcast_to_conversation(conn, conversation_id, "conversation_updated", {"conversationId": conversation_id})

    if old_image and old_image != DEFAULT_PROFILE_IMAGE:
        delete_image_file(old_image)

    return jsonify({"success": True, "profile_image": new_path})


@app.route("/api/conversations/<int:conversation_id>/photo", methods=["DELETE"])
@login_required_api
def delete_group_photo(conversation_id):
    user_id = session["user_id"]

    with get_db() as conn:
        conv = conn.execute(
            "SELECT is_group, owner_id, profile_image FROM conversations WHERE id = %s", (conversation_id,)
        ).fetchone()
        if not conv or not conv["is_group"]:
            return jsonify({"success": False, "error": "그룹 채팅만 사진을 삭제할 수 있습니다."}), 400
        if conv["owner_id"] != user_id:
            return jsonify({"success": False, "error": "방장만 그룹 사진을 삭제할 수 있습니다."}), 403

        old_image = conv["profile_image"]
        conn.execute("UPDATE conversations SET profile_image = %s WHERE id = %s", (DEFAULT_PROFILE_IMAGE, conversation_id))
        conn.commit()
        broadcast_to_conversation(conn, conversation_id, "conversation_updated", {"conversationId": conversation_id})

    if old_image and old_image != DEFAULT_PROFILE_IMAGE:
        delete_image_file(old_image)

    return jsonify({"success": True, "profile_image": DEFAULT_PROFILE_IMAGE})


def send_verification_email(email, code):
    resend.Emails.send({
        "from": get_resend_sender(),
        "to": email,
        "subject": "이메일 인증 코드",
        "html": f"<p>인증 코드: <strong>{code}</strong></p><p>3분 이내에 입력해주세요.</p>",
    })


def get_resend_sender():
    """Resend에서 인증한 발신 주소만 사용해 메일이 조용히 실패하지 않게 한다."""
    sender = os.environ.get("RESEND_FROM_EMAIL")
    if not sender:
        raise RuntimeError("RESEND_FROM_EMAIL 환경변수가 설정되지 않았습니다.")
    return sender


def send_password_reset_email(email, code):
    resend.Emails.send({
        "from": get_resend_sender(),
        "to": email,
        "subject": "클라우드 채팅 비밀번호 재설정 코드",
        "html": (
            "<p>비밀번호 재설정 코드입니다.</p>"
            f"<p>인증 코드: <strong>{code}</strong></p>"
            "<p>3분 이내에 입력해주세요.</p>"
        ),
    })

@app.route("/api/password-reset/send-code", methods=["POST"])
def send_password_reset_code():
    email = (request.get_json() or {}).get("email", "").strip().lower()

    # 계정 존재 여부를 노출하지 않는 공통 안내 문구
    message = "입력한 이메일로 가입된 계정이 있다면 인증 코드를 보냈습니다."

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": True, "message": message})

    with get_db() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE email = %s",
            (email,)
        ).fetchone()

        if not user:
            return jsonify({"success": True, "message": message})

        code = f"{random.randint(0, 999999):06d}"
        kst = timezone(timedelta(hours=9))
        expires_at = (
            datetime.now(kst) + timedelta(minutes=3)
        ).strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "DELETE FROM password_reset_codes WHERE email = %s",
            (email,)
        )
        conn.execute(
            """
            INSERT INTO password_reset_codes
                (email, code, expires_at, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (email, code, expires_at, now_str())
        )
        conn.commit()

    try:
        send_password_reset_email(email, code)
    except Exception:
        app.logger.exception("비밀번호 재설정 메일 발송 실패")
        # 이전에는 실패해도 성공 문구를 돌려줘서 사용자가 원인을 알 수 없었다.
        return jsonify({"success": False, "error": "인증번호 이메일 전송에 실패했습니다. 관리자에게 문의해주세요."}), 503

    return jsonify({"success": True, "message": message})

@app.route("/api/password-reset/confirm", methods=["POST"])
def confirm_password_reset():
    data = request.get_json() or {}

    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    new_password = data.get("new_password") or ""

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": False, "error": "올바른 이메일 주소를 입력해주세요."}), 400

    if not re.fullmatch(
        r"(?=.*[a-z])(?=.*[0-9])(?=.*[^a-zA-Z0-9]).{7,}",
        new_password
    ):
        return jsonify({
            "success": False,
            "error": "비밀번호는 영문 소문자, 숫자, 특수문자를 포함해 7자 이상이어야 합니다."
        }), 400

    with get_db() as conn:
        reset_code = conn.execute(
            """
            SELECT * FROM password_reset_codes
            WHERE email = %s AND code = %s
            """,
            (email, code)
        ).fetchone()

        if not reset_code:
            return jsonify({
                "success": False,
                "error": "인증번호가 올바르지 않습니다."
            }),400

        if reset_code["expires_at"] < now_str():
            return jsonify({
                "success": False,
                "error": "인증번호가 만료되었습니다. 다시 요청해주세요."
            }),400

        conn.execute(
            "UPDATE users SET password_hash = %s WHERE email = %s",
            (generate_password_hash(new_password), email)
        )
        conn.execute(
            "DELETE FROM password_reset_codes WHERE email = %s",
            (email,)
        )
        conn.commit()

    return jsonify({"success": True})

def send_username_reminder_email(email, username):
    resend.Emails.send({
        "from": get_resend_sender(),
        "to": email,
        "subject": "클라우드 채팅 아이디 안내",
        "html": (
            "<p>요청하신 아이디 안내입니다.</p>"
            f"<p>아이디: <strong>{username}</strong></p>"
        ),
    })

@app.route("/api/find-username", methods=["POST"])
def find_username():
    email = (request.get_json() or {}).get("email", "").strip().lower()

    # 이메일 형식이 틀려도 동일한 응답을 보내 계정 존재 여부를 감춥니다.
    message = "입력한 이메일로 가입된 계정이 있다면 아이디 안내 메일을 보냈습니다."

    if not re.fullmatch(r"[^@]+@[^@]+\.[^@]+", email):
        return jsonify({"success": True, "message": message})

    with get_db() as conn:
        user = conn.execute(
            "SELECT username FROM users WHERE email = %s",
            (email,)
        ).fetchone()

    if user:
        try:
            send_username_reminder_email(email, user["username"])
        except Exception:
            app.logger.exception("아이디 안내 이메일 발송 실패")
            return jsonify({"success": False, "error": "아이디 안내 이메일 전송에 실패했습니다. 관리자에게 문의해주세요."}), 503

    return jsonify({"success": True, "message": message})


@app.route("/api/send-verification-code", methods=["POST"])
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
            (email, code, expires_at, now_str())
        )
        conn.commit()

    try:
        send_verification_email(email, code)
    except Exception:
        app.logger.exception("이메일 발송 실패 (email=%s)", email)
        return jsonify({"success": False, "error": "이메일 전송에 실패했습니다. 잠시 후 다시 시도해주세요."}), 500

    return jsonify({"success": True, "message": "인증 코드가 이메일로 전송되었습니다."})


@app.route("/api/verify-email-code", methods=["POST"])
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
        return jsonify({"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."}), 400
    return jsonify({"success": True, "message": "이메일 인증이 완료되었습니다."})

@app.route("/api/account/email/send-code", methods=["POST"])
@login_required_api
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
            (new_email, code, expires_at, now_str())
        )
        conn.commit()

    try:
        send_verification_email(new_email, code)
    except Exception:
        app.logger.exception("이메일 발송 실패 (email=%s)", new_email)
        return jsonify({"success": False, "error": "이메일 전송에 실패했습니다. 잠시 후 다시 시도해주세요."}), 500

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
            (new_email, code)
        ).fetchone()
        if not verification:
            return jsonify({"success": False, "error": "인증번호가 올바르지 않습니다."})
        if verification["expires_at"] < now_str():
            return jsonify({"success": False, "error": "인증번호가 만료되었습니다. 다시 요청해주세요."})

        # 코드 발송 이후 다른 사람이 선점했을 수도 있으니 한 번 더 체크
        existing = conn.execute(
            "SELECT id FROM users WHERE email = %s AND id != %s", (new_email, user_id)
        ).fetchone()
        if existing:
            return jsonify({"success": False, "error": "이미 사용 중인 이메일입니다."})

        conn.execute("UPDATE users SET email = %s WHERE id = %s", (new_email, user_id))
        conn.execute("DELETE FROM email_verification_codes WHERE email = %s", (new_email,))
        conn.commit()

    session["email"] = new_email
    return jsonify({"success": True, "email": new_email})


@app.route("/api/conversations/<int:conversation_id>/read", methods=["POST"])
@login_required_api
def read_conversation(conversation_id):
    user_id = session["user_id"]

    with get_db() as conn:
        if not get_membership(conn, conversation_id, user_id):
            return jsonify({"success": False, "error": "대화방을 찾을 수 없습니다."}), 404

        latest = conn.execute(
            "SELECT MAX(id) AS max_id FROM messages WHERE conversation_id = %s", (conversation_id,)
        ).fetchone()
        latest_id = latest["max_id"] or 0 if latest else 0

        conn.execute(
            "UPDATE conversation_members SET last_read_message_id = %s WHERE conversation_id = %s AND user_id = %s",
            (latest_id, conversation_id, user_id)
        )
        conn.commit()
    return jsonify({"success": True})


# 서버 실행 시 DB 테이블 자동 생성
try:
    init_db()
except Exception as e:
    app.logger.warning("초기 DB 생성 실패 (서버 연결 대기 중일 수 있음): %s", e)


if __name__ == "__main__":
    socketio.run(app, debug=True)

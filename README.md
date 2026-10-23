# Cloud Chatting

친구와 메시지, 사진, 파일을 편안하게 주고받는 **실시간 웹 메신저**입니다.
설치 없이 브라우저에서 바로 쓰고, PC와 모바일 화면을 모두 지원합니다.

- 서비스: https://cloudchatting.com
- 스택: Flask · Flask-SocketIO · PostgreSQL · 순수 JavaScript(프레임워크 없음)

## 주요 기능

**대화**
- 1:1 채팅과 그룹 채팅(방 이름·사진, 멤버 초대·내보내기, 방장 위임, 그룹 종료)
- 실시간 전달, 안 읽은 메시지 수 표시, 상대의 접속 상태(온라인/오프라인)
- 메시지 답장 · 수정 · 삭제 · 고정 · 이모지 공감 · 다른 대화방으로 전달 · 신고
- 사진 · 파일 · 동영상 · 음성 메시지 첨부, 링크 미리보기
- 대화방 숨기기 · 알림 끄기 · 상단 고정, 사진 모아보기
- 웹 푸시 알림

**친구와 계정**
- 아이디 검색으로 친구 요청 · 수락 · 거절, 차단과 차단 해제
- 이메일 인증 회원가입, 아이디 찾기, 비밀번호 재설정
- 프로필 사진(원형 자르기) · 배경 사진 · 소개글 · 프로필 공개 범위
- 정지 계정 처리, 비밀번호 변경 시 다른 기기 로그아웃

**화면**
- 대화방별 채팅 테마(하트, 곰, 오로라, 크리스마스, 할로윈, 계절 테마 등)와 클라우드(Liquid Glass) 화면 테마
- 다크 모드, 업무용 **오피스 모드**(글자 크기·밀도·대비·움직임 줄이기 설정)
- 한국어 · English · 中文 · 日本語 · Español
- PC는 3단 레이아웃, 모바일은 하단 탭바와 목록 → 대화 전환

**운영**
- 관리자 콘솔: 공지사항, 고객 문의 답변, 신고 처리(경고·기간 정지·영구 정지), 사용자·리뷰 관리, 접속자와 서버 오류 로그
- 관리자 페이지는 관리자 계정 + 별도 접근 키(30분 인증)를 모두 통과해야 열립니다.
- 사용자 리뷰, 고객 문의, 공지사항 · 업데이트 기록

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| 서버 | Python 3.12, Flask, Flask-Login, Flask-SocketIO(threading), gunicorn(gthread) |
| DB | PostgreSQL (psycopg2 연결 풀), Alembic(기준 버전 관리) |
| 프런트엔드 | HTML · CSS · JavaScript (빌드 도구 없음), socket.io 클라이언트, Font Awesome |
| 외부 서비스 | Resend(메일), Cloudinary(파일 저장), Web Push(VAPID), Sentry(오류 추적) |
| 품질 | unittest, ruff, black, GitHub Actions |
| 배포 | Render |

## 프로젝트 구조

```
app.py              Flask 앱 진입점 · 소켓 이벤트 · 아직 분리되지 않은 라우트와 헬퍼
config.py           환경 변수를 읽는 설정 객체
extensions.py       Flask-Login 등 확장 초기화
blueprints/         URL 연결 계층 (auth, chat, friends, profile, support, admin)
services/           비즈니스 규칙 (인증, 가입, 채팅, 메시지, 친구, 관리자, 비밀번호 정책)
repositories/       DB 조회 (사용자)
models/             User 모델
templates/          index(메신저), login(소개 + 로그인·회원가입, /와 /login 공용), admin, admin_verify, legal
static/             css/style.css, js/script.js · i18n.js · liquid-glass.js, push-sw.js(서비스 워커)
migrations/         Alembic 환경과 기준 버전, manual/ 에 수동 실행 SQL
tests/              unit (서비스·모델·저장소), integration (페이지·접근 통제·스키마)
documents/          운영 기준 문서와 작동 구조 안내서
```

`app.py`는 단계적으로 `services/` · `blueprints/` 로 분리하는 중입니다. 새 기능은 가능하면 서비스 계층에 규칙을 두고 블루프린트에서 연결합니다.

## 로컬에서 실행하기

필요한 것: Python 3.12, PostgreSQL

```bash
git clone https://github.com/bs7272u7/messenger-beta.git
cd messenger-beta

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env               # 값을 채웁니다 (아래 환경 변수 참고)
```

데이터베이스를 하나 만든 뒤(`createdb messenger_beta`) 실행합니다. 테이블은 서버가 시작될 때 `init_db()`가 자동으로 만들고,
DB가 아직 준비되지 않았다면 백그라운드에서 준비될 때까지 다시 시도합니다.

```bash
python app.py                      # 개발 서버
# 운영과 같은 방식: gunicorn --worker-class gthread --workers 1 --threads 24 app:app
```

> 가입 인증번호는 Resend로 보내는 메일로만 전달됩니다. 로컬에서 회원가입까지 확인하려면 `RESEND_API_KEY`와 `RESEND_FROM_EMAIL`을 설정해야 합니다.

### 환경 변수

`.env.example`을 복사해서 사용합니다. `.env`는 **절대 커밋하지 않습니다.**

| 변수 | 설명 |
|---|---|
| `SECRET_KEY` | 세션 서명 키. 운영에서는 필수이며 없으면 서버가 시작되지 않습니다. `python -c "import secrets; print(secrets.token_hex(32))"` 로 만듭니다. |
| `DATABASE_URL` 또는 `DB_HOST` `DB_PORT` `DB_NAME` `DB_USER` `DB_PASSWORD` `DB_SSLMODE` | DB 연결. `DATABASE_URL`이 있으면 우선 사용합니다. |
| `ADMIN_EMAIL` | 이 이메일로 가입한 계정이 관리자가 됩니다. |
| `ADMIN_ACCESS_KEY_HASH` | 관리자 페이지 접근 키의 해시(Werkzeug 형식). `python -c "from werkzeug.security import generate_password_hash as g; print(g('원하는 키'))"` 로 만듭니다. 없으면 관리자 보안 확인 화면에 설정 안내가 나옵니다. |
| `SUPPORT_EMAIL` | 고객 문의 수신 주소 |
| `RESEND_API_KEY` `RESEND_FROM_EMAIL` | 인증번호·안내 메일 발송 |
| `CLOUDINARY_CLOUD_NAME` `CLOUDINARY_API_KEY` `CLOUDINARY_API_SECRET` | 파일 저장소. 셋 다 설정하면 Cloudinary, 아니면 `static/uploads`에 저장합니다. |
| `VAPID_PUBLIC_KEY` `VAPID_PRIVATE_KEY` `VAPID_CLAIMS_EMAIL` | 웹 푸시 알림 |
| `SENTRY_DSN` | 오류 추적(선택) |
| `SESSION_COOKIE_SECURE` | HTTPS에서만 쿠키 전송. Render에서는 자동으로 켜집니다. |
| `GITHUB_REPOSITORY` `GITHUB_TOKEN` | 업데이트 기록 조회(선택) |

## 테스트와 코드 검사

```bash
python -m ruff check blueprints services repositories models tests/unit tests/integration
python -m black --check blueprints services repositories models tests/unit tests/integration
python -m unittest discover -s tests -v
```

DB 연결 정보(`DATABASE_URL` 또는 `DB_PASSWORD`)가 있으면 스키마 통합 테스트도 함께 실행되고, 없으면 그 테스트만 건너뜁니다.
같은 검사가 GitHub Actions(`.github/workflows/ci.yml`)에서 push와 pull request마다 실행됩니다.

## 배포 (Render)

1. Render에서 PostgreSQL을 만들고 Web Service를 연결합니다. 시작 명령은 `Procfile`을 따릅니다.
2. Web Service의 Environment에 위 환경 변수를 설정합니다. 특히 `SECRET_KEY`, `DATABASE_URL`, `ADMIN_EMAIL`, `ADMIN_ACCESS_KEY_HASH`, `RESEND_API_KEY`는 꼭 필요합니다.
3. `main` 브랜치에 머지하면 배포됩니다. 상태 확인은 `/healthz` 입니다.
4. 정적 파일(`style.css`, `script.js`, `i18n.js`)을 고쳤다면 `templates/index.html`의 `?v=` 값을 올려 브라우저 캐시를 갱신합니다.

배포 전 점검 목록과 운영 기준은 [`documents/backend_operations.md`](documents/backend_operations.md)를 참고하세요.

### 데이터베이스 변경

- 새 컬럼은 `init_db()`의 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`로 추가합니다(기존 DB와 호환).
- 스키마 변경은 Alembic revision으로 관리하는 방향으로 전환 중입니다. 절차는 [`migrations/README.md`](migrations/README.md)를 참고하세요.
- 운영 DB를 건드리는 수동 SQL은 `migrations/manual/`에 두며, 실행 전에 반드시 백업합니다.

## 보안 메모

- 상태를 바꾸는 API는 CSRF 토큰(`X-CSRF-Token`)을 확인합니다.
- 로그인 세션은 계정별 토큰과 함께 검증하므로, DB를 새로 만들어도 이전 쿠키가 다른 계정으로 인식되지 않습니다. 비밀번호를 바꾸면 다른 기기의 로그인이 끊깁니다.
- 로그인, 회원가입, 인증번호 요청, 비밀번호 재설정, 관리자 접근 키 확인에는 IP 단위 요청 제한이 있습니다(서버 메모리 기준이라 재시작하면 초기화됩니다).
- 사용자 입력은 `innerHTML`에 넣기 전에 `escapeHTML`을 거칩니다.
- 업로드 이미지는 크기와 픽셀 수를 제한하고 Pillow로 검증합니다.

## 라이선스와 출처

- `static/js/liquid-glass.js`는 MIT 라이선스 외부 코드입니다(파일 상단의 라이선스 표기 참고).
- 일부 아이콘은 [Icons8](https://icons8.com)의 무료 아이콘이며, 앱 내 도움말에 출처를 표기했습니다.

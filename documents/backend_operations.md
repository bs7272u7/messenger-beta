# Cloud Chatting 백엔드 운영 기준

## 환경 변수

로컬 개발은 `.env.example`을 복사하여 `.env`를 만든 후 필요한 값을 채웁니다. `.env`는 절대 커밋하지 않습니다.

운영 환경에서는 `SECRET_KEY`, DB 연결 정보, 관리자 접근 키 해시를 반드시 별도의 비밀 관리 기능으로 설정합니다. 코드에 DB 비밀번호나 API 키를 기본값으로 두지 않습니다.

## 검증 명령

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check blueprints services repositories models tests/unit tests/integration
.\.venv\Scripts\python.exe -m black --check blueprints services repositories models tests/unit tests/integration
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

DB 연결 정보가 있는 개발 환경에서는 핵심 테이블 존재 여부도 통합 테스트로 확인합니다. CI처럼 DB가 없는 환경에서는 해당 검증만 건너뜁니다.

## 배포 전 점검

1. URL 중복 검사와 테스트를 통과시킵니다.
2. 운영 환경에서 `SECRET_KEY`와 DB 비밀번호가 설정됐는지 확인합니다.
3. DB 백업이 최근 상태인지 확인합니다.
4. Sentry, 메일, 파일 저장소, 웹 푸시 키가 환경별로 올바른지 확인합니다.
5. `/api/` 상태 변경 요청의 CSRF 검증과 관리자 추가 인증을 확인합니다.
6. `/healthz`가 `200`과 `{"status":"ok","database":"available"}`을 반환하는지 확인합니다.

## 실시간 서버

현재 앱은 Flask-SocketIO의 `threading` 모드와 Gunicorn `gthread` 워커를 사용합니다. 따라서 `eventlet`은 설치하지 않습니다. 다중 인스턴스 확장이 필요해질 때는 Redis 메시지 큐와 고정 세션(sticky session)을 함께 구성한 뒤 별도 스테이징 부하 검증을 진행합니다.

## 데이터베이스 전환 원칙

현재 자동 테이블 생성 방식에서 Alembic 마이그레이션으로 전환할 때는 운영 DB에 즉시 적용하지 않습니다. 먼저 스테이징 DB에서 현재 스키마를 기준 마이그레이션으로 고정하고, 이후 변경부터 버전 파일로 적용합니다.

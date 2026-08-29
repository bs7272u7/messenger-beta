# 데이터베이스 마이그레이션 전환 절차

현재 서비스는 `app.py`의 `init_db()`로 기존 PostgreSQL 스키마 호환을 유지합니다.
운영 데이터가 있는 상태에서 이를 즉시 제거하거나 자동 변환하지 않습니다.

## 기준 스키마 고정

1. 운영 DB를 백업합니다.
2. 동일한 백업을 복원한 스테이징 DB에서 앱을 기동하고 `/healthz`와 통합 테스트를 확인합니다.
3. 스테이징 DB의 스키마를 기준 버전으로 기록합니다.
4. 이후 스키마 변경은 반드시 버전 파일과 롤백 절차를 함께 검토합니다.

## Alembic 사용

`alembic.ini`과 `migrations/versions/20260829_01_baseline.py`는 기존 PostgreSQL 스키마를 데이터 변경 없이 기준 버전으로 표시합니다.
스테이징 DB에서만 아래 명령으로 현재 스키마를 기준 버전에 연결합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql://..."
.\.venv\Scripts\alembic.exe stamp 20260829_01
.\.venv\Scripts\alembic.exe current
```

새 스키마 변경은 기준 버전 이후에만 `alembic revision`으로 추가합니다. 운영 DB에서 `stamp` 또는 `upgrade`를 실행하기 전에는 반드시 백업과 스테이징 검증을 완료합니다.

## 적용 전 필수 확인

- 운영 DB에 직접 `DROP`, `TRUNCATE`, 대량 `DELETE`를 실행하지 않습니다.
- 마이그레이션은 먼저 스테이징에서 적용·롤백을 모두 검증합니다.
- 배포 전후 `tests/integration/test_database_schema.py`와 `/healthz`를 확인합니다.
- `init_db()` 제거는 모든 기존 환경이 기준 버전으로 표시된 뒤에만 별도 변경으로 진행합니다.

이 절차는 기존 데이터 보존이 우선이며, 실제 버전 관리 도구 도입은 스테이징 DB 준비 후 별도 커밋으로 진행합니다.

"""Alembic 환경 설정. DB URL은 저장소가 아닌 환경 변수(DATABASE_URL)에서만 읽는다."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# 자동 생성(autogenerate)은 쓰지 않는다. 스키마는 app.py의 init_db()가 만들고, 이후 변경만 수동 revision으로 추가한다.
target_metadata = None


def run_migrations_offline() -> None:
    """오프라인 모드: DB에 연결하지 않고 SQL 스크립트만 만든다(literal_binds로 값을 SQL에 직접 넣는다)."""
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인 모드: 실제 DB에 연결해 마이그레이션을 실행한다. 풀을 쓰지 않는(NullPool) 일회용 연결이다."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

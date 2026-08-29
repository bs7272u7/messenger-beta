"""existing PostgreSQL schema baseline

Revision ID: 20260829_01
Revises:
Create Date: 2026-08-29
"""

revision = "20260829_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 init_db() 스키마를 기준으로 표시만 한다."""


def downgrade() -> None:
    """기준 버전은 데이터 변경을 수행하지 않는다."""

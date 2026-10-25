"""DB 스키마 통합 테스트. 실제 PostgreSQL에 연결되는 환경에서만 실행한다."""

import os
import unittest

import app as application_module


class DatabaseSchemaTests(unittest.TestCase):
    """init_db()가 핵심 테이블을 모두 만들었는지 확인한다."""

    @classmethod
    def setUpClass(cls):
        """DATABASE_URL 또는 DB_PASSWORD가 없으면(예: CI의 단위 테스트 단계) 이 클래스 전체를 건너뛴다."""
        if not (os.environ.get("DATABASE_URL") or os.environ.get("DB_PASSWORD")):
            raise unittest.SkipTest("DB 연결 정보가 없어 스키마 통합 테스트를 건너뜁니다.")

    def test_core_tables_exist(self):
        """서비스 동작에 필요한 핵심 테이블이 public 스키마에 존재하는지 확인한다."""
        expected_tables = {
            "users",
            "conversations",
            "conversation_members",
            "messages",
            "friend_requests",
            "follows",
            "follow_requests",
            "blocks",
            "support_inquiries",
            "reports",
            "notices",
            "reviews",
        }

        with application_module.get_db() as conn:
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            ).fetchall()

        actual_tables = {row["table_name"] for row in rows}
        self.assertTrue(expected_tables.issubset(actual_tables))


if __name__ == "__main__":
    unittest.main()

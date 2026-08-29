import os
import unittest

import app as application_module


class DatabaseSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (os.environ.get("DATABASE_URL") or os.environ.get("DB_PASSWORD")):
            raise unittest.SkipTest("DB 연결 정보가 없어 스키마 통합 테스트를 건너뜁니다.")

    def test_core_tables_exist(self):
        expected_tables = {
            "users",
            "conversations",
            "conversation_members",
            "messages",
            "friend_requests",
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

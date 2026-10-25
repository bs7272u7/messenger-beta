"""FollowService 단위 테스트. DB를 쓰지 않는 입력 검증 경로만 확인한다."""

import unittest

from services.follow_service import FollowService, FollowServiceError, escape_like


class FollowServiceTests(unittest.TestCase):
    """입력 검증은 DB에 접근하기 전에 끝나야 한다. setUp의 연결 팩토리는 호출되면 즉시 실패해 그 점을 보장한다."""

    def setUp(self):
        """연결 팩토리가 호출되면 테스트가 실패하도록 해서, 검증 단계에서 DB를 건드리지 않음을 확인한다."""
        self.service = FollowService(
            lambda: self.fail("DB 연결이 호출되면 안 됩니다."),
            lambda: "2026-10-26 12:00:00",
            lambda *_: False,
        )

    def test_request_follow_rejects_self(self):
        """자기 자신은 팔로우할 수 없다."""
        with self.assertRaisesRegex(FollowServiceError, "자기 자신"):
            self.service.request_follow(1, 1)

    def test_request_follow_rejects_non_integer_target(self):
        """대상 ID가 정수가 아니면(불리언 포함) 거부한다."""
        for bad in ("2", None, True, 1.5):
            with self.assertRaises(FollowServiceError):
                self.service.request_follow(1, bad)

    def test_find_users_rejects_short_query(self):
        """너무 짧은 검색어는 계정을 훑는 데 쓰일 수 있어 DB 조회 없이 거부한다."""
        with self.assertRaisesRegex(FollowServiceError, "2글자"):
            self.service.find_users(1, " a ")

    def test_list_relations_rejects_unknown_kind(self):
        """목록 종류는 followers·following만 허용한다."""
        with self.assertRaises(FollowServiceError):
            self.service.list_relations(1, 2, "friends")

    def test_escape_like_neutralizes_wildcards(self):
        """검색어의 %와 _가 와일드카드로 쓰이지 않게 이스케이프한다."""
        self.assertEqual(escape_like("a%b_c\\"), "a\\%b\\_c\\\\")


if __name__ == "__main__":
    unittest.main()

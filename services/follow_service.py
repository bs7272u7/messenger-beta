"""팔로우 요청, 팔로우 관계, 사용자 검색, 프로필 요약을 관리하는 서비스.

모던 UI의 관계 모델이다. 팔로우는 항상 '요청 → 수락'으로 맺어지고(follow_requests), 수락되면 한쪽 방향 관계(follows)가 생긴다.
기존 친구 기능(friend_requests)과는 서로 독립이라, 한쪽을 바꿔도 다른 쪽이 따라 바뀌지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass


class FollowServiceError(Exception):
    """팔로우 기능의 예상 가능한 검증 오류. HTTP 상태 코드를 함께 담아 블루프린트가 그대로 응답에 쓴다."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FollowRequestOutcome:
    """팔로우 요청·응답 처리 결과. notify_user_id는 실시간 알림을 보낼 상대 사용자 ID."""

    notify_user_id: int


MAX_PAGE_SIZE = 50
MIN_SEARCH_LENGTH = 2


def escape_like(text: str) -> str:
    """LIKE 검색에서 %, _ 가 와일드카드로 해석되지 않게 이스케이프한다."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class FollowService:
    """팔로우 요청과 관계, 사용자 검색을 DB 연결 하나로 처리한다."""

    def __init__(self, connection_factory, now_string, blocked_either_way) -> None:
        """서비스가 쓸 DB 연결과 보조 함수를 주입받는다.

        Args:
            connection_factory: DB 연결을 만들어 주는 함수.
            now_string: 현재 시각 문자열을 돌려주는 함수.
            blocked_either_way: 두 사용자 중 한쪽이라도 상대를 차단했는지 확인하는 함수.
        """
        self._connection_factory = connection_factory
        self._now_string = now_string
        self._blocked_either_way = blocked_either_way

    # ------------------------------------------------------------------
    # 관계 조회
    # ------------------------------------------------------------------
    @staticmethod
    def is_following(conn, follower_id: int, followee_id: int) -> bool:
        """follower가 followee를 팔로우 중인지 확인한다."""
        return (
            conn.execute(
                "SELECT 1 FROM follows WHERE follower_id = %s AND followee_id = %s",
                (follower_id, followee_id),
            ).fetchone()
            is not None
        )

    @classmethod
    def is_mutual(cls, conn, user_a: int, user_b: int) -> bool:
        """서로 팔로우하는 사이(맞팔)인지 확인한다."""
        return cls.is_following(conn, user_a, user_b) and cls.is_following(conn, user_b, user_a)

    @staticmethod
    def has_pending_request(conn, requester_id: int, target_id: int) -> bool:
        """requester가 target에게 보낸 수락 대기 중인 팔로우 요청이 있는지 확인한다."""
        return (
            conn.execute(
                "SELECT 1 FROM follow_requests WHERE requester_id = %s AND target_id = %s",
                (requester_id, target_id),
            ).fetchone()
            is not None
        )

    def relation(self, conn, viewer_id: int, target_id: int) -> dict:
        """viewer 입장에서 본 target과의 관계.

        Returns:
            status: self / following / requested / none.
            followsMe: 상대가 나를 팔로우 중인지. requestedMe: 상대가 나에게 보낸 요청이 대기 중인지.
        """
        if viewer_id == target_id:
            return {"status": "self", "followsMe": False, "requestedMe": False}
        if self.is_following(conn, viewer_id, target_id):
            status = "following"
        elif self.has_pending_request(conn, viewer_id, target_id):
            status = "requested"
        else:
            status = "none"
        return {
            "status": status,
            "followsMe": self.is_following(conn, target_id, viewer_id),
            "requestedMe": self.has_pending_request(conn, target_id, viewer_id),
        }

    @classmethod
    def can_view_details(cls, conn, viewer_id: int, target) -> bool:
        """viewer가 target의 상세(소개글·커버·팔로워/팔로잉 목록)를 볼 수 있는지 판단한다.

        본인이거나, 전체 공개이거나, 팔로우가 수락된 사람이면 볼 수 있다. 그 외(비공개 포함)는 기본 정보만 볼 수 있다.
        """
        if viewer_id == target["id"] or target["profile_visibility"] == "public":
            return True
        return cls.is_following(conn, viewer_id, target["id"])

    def _visible_user(self, conn, viewer_id: int, target_id: int):
        """상대 사용자를 가져온다. 없거나 정지됐거나 차단 관계면 '없는 사용자'와 같은 404를 낸다."""
        target = conn.execute(
            "SELECT id, username, display_name, profile_image, cover_image, bio, profile_visibility, is_suspended"
            " FROM users WHERE id = %s",
            (target_id,),
        ).fetchone()
        if (
            not target
            or target["is_suspended"]
            or (viewer_id != target_id and self._blocked_either_way(conn, viewer_id, target_id))
        ):
            raise FollowServiceError("사용자를 찾을 수 없습니다.", 404)
        return target

    # ------------------------------------------------------------------
    # 프로필 요약
    # ------------------------------------------------------------------
    def summary_by_username(self, viewer_id: int, username: str) -> dict:
        """아이디로 프로필 요약을 돌려준다(프로필 페이지 주소 /u/<아이디>용). 없으면 404."""
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE username = %s", ((username or "").strip().lower(),)
            ).fetchone()
        if not row:
            raise FollowServiceError("사용자를 찾을 수 없습니다.", 404)
        return self.summary(viewer_id, row["id"])

    def summary(self, viewer_id: int, target_id: int) -> dict:
        """프로필 화면에 필요한 정보를 돌려준다. 상세를 볼 수 없으면 소개글과 커버를 비운다."""
        with self._connection_factory() as conn:
            target = self._visible_user(conn, viewer_id, target_id)
            can_view = self.can_view_details(conn, viewer_id, target)
            counts = conn.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM follows f JOIN users u ON u.id = f.follower_id
                      WHERE f.followee_id = %s AND NOT u.is_suspended) AS followers,
                    (SELECT COUNT(*) FROM follows f JOIN users u ON u.id = f.followee_id
                      WHERE f.follower_id = %s AND NOT u.is_suspended) AS following
                """,
                (target_id, target_id),
            ).fetchone()
            return {
                "id": target["id"],
                "username": target["username"],
                "displayName": target["display_name"] or target["username"],
                "profileImage": target["profile_image"],
                "coverImage": target["cover_image"] if can_view else None,
                "bio": (target["bio"] or "") if can_view else "",
                "visibility": "public" if target["profile_visibility"] == "public" else "private",
                "canViewDetails": can_view,
                "followerCount": counts["followers"],
                "followingCount": counts["following"],
                "relation": self.relation(conn, viewer_id, target_id),
            }

    # ------------------------------------------------------------------
    # 팔로우 요청
    # ------------------------------------------------------------------
    def request_follow(self, requester_id: int, target_id) -> FollowRequestOutcome:
        """팔로우 요청을 보낸다. 상대 메시지함에 수락 대기 요청이 생긴다.

        Raises:
            FollowServiceError: 자기 자신·없는 사용자·차단 관계·이미 팔로우 중·이미 요청한 경우.
        """
        if not isinstance(target_id, int) or isinstance(target_id, bool):
            raise FollowServiceError("올바른 사용자가 아닙니다.")
        if target_id == requester_id:
            raise FollowServiceError("자기 자신은 팔로우할 수 없습니다.")
        with self._connection_factory() as conn:
            self._visible_user(conn, requester_id, target_id)
            if self.is_following(conn, requester_id, target_id):
                raise FollowServiceError("이미 팔로우 중입니다.", 409)
            if self.has_pending_request(conn, requester_id, target_id):
                raise FollowServiceError("이미 팔로우 요청을 보냈습니다.", 409)
            conn.execute(
                "INSERT INTO follow_requests (requester_id, target_id, created_at) VALUES (%s, %s, %s)",
                (requester_id, target_id, self._now_string()),
            )
            conn.commit()
        return FollowRequestOutcome(notify_user_id=target_id)

    def unfollow_or_cancel(self, user_id: int, target_id: int) -> FollowRequestOutcome:
        """팔로우를 끊거나, 아직 수락되지 않은 내 요청을 취소한다. 둘 다 없으면 아무것도 하지 않는다."""
        with self._connection_factory() as conn:
            conn.execute(
                "DELETE FROM follows WHERE follower_id = %s AND followee_id = %s",
                (user_id, target_id),
            )
            conn.execute(
                "DELETE FROM follow_requests WHERE requester_id = %s AND target_id = %s",
                (user_id, target_id),
            )
            conn.commit()
        return FollowRequestOutcome(notify_user_id=target_id)

    def remove_follower(self, user_id: int, follower_id: int) -> FollowRequestOutcome:
        """나를 팔로우하는 사람을 끊는다('삭제' 버튼). 상대가 다시 요청하면 새 요청으로 처리된다."""
        with self._connection_factory() as conn:
            conn.execute(
                "DELETE FROM follows WHERE follower_id = %s AND followee_id = %s",
                (follower_id, user_id),
            )
            conn.commit()
        return FollowRequestOutcome(notify_user_id=follower_id)

    def respond(self, user_id: int, request_id: int, accept: bool) -> FollowRequestOutcome:
        """받은 팔로우 요청을 수락하거나 거절한다. 수락하면 follows에 관계가 생기고, 어느 쪽이든 요청은 지워진다.

        Raises:
            FollowServiceError: 요청이 없거나 내 요청이 아닌 경우(404).
        """
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT requester_id, target_id FROM follow_requests WHERE id = %s",
                (request_id,),
            ).fetchone()
            if not row or row["target_id"] != user_id:
                raise FollowServiceError("요청을 찾을 수 없습니다.", 404)
            conn.execute("DELETE FROM follow_requests WHERE id = %s", (request_id,))
            if accept and not self._blocked_either_way(conn, user_id, row["requester_id"]):
                conn.execute(
                    "INSERT INTO follows (follower_id, followee_id, created_at) VALUES (%s, %s, %s)"
                    " ON CONFLICT DO NOTHING",
                    (row["requester_id"], user_id, self._now_string()),
                )
            conn.commit()
        return FollowRequestOutcome(notify_user_id=row["requester_id"])

    def list_requests(self, user_id: int) -> dict:
        """내가 받은 팔로우 요청과 내가 보낸 팔로우 요청(수락 대기)을 돌려준다."""
        with self._connection_factory() as conn:
            incoming = conn.execute(
                """
                SELECT r.id, r.created_at, u.id AS user_id, u.username, u.display_name, u.profile_image
                FROM follow_requests r JOIN users u ON u.id = r.requester_id
                WHERE r.target_id = %s AND NOT u.is_suspended
                ORDER BY r.id DESC
                """,
                (user_id,),
            ).fetchall()
            outgoing = conn.execute(
                """
                SELECT r.id, r.created_at, u.id AS user_id, u.username, u.display_name, u.profile_image
                FROM follow_requests r JOIN users u ON u.id = r.target_id
                WHERE r.requester_id = %s AND NOT u.is_suspended
                ORDER BY r.id DESC
                """,
                (user_id,),
            ).fetchall()
        return {
            "incoming": [self._request_dict(row) for row in incoming],
            "outgoing": [self._request_dict(row) for row in outgoing],
        }

    @staticmethod
    def _request_dict(row) -> dict:
        return {
            "id": row["id"],
            "createdAt": row["created_at"],
            "user": {
                "id": row["user_id"],
                "username": row["username"],
                "displayName": row["display_name"] or row["username"],
                "profileImage": row["profile_image"],
            },
        }

    def incoming_request_count(self, user_id: int) -> int:
        """내가 받은 팔로우 요청 수(메시지함 배지용)."""
        with self._connection_factory() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM follow_requests WHERE target_id = %s", (user_id,)
            ).fetchone()
        return row["n"]

    # ------------------------------------------------------------------
    # 팔로워·팔로잉 목록, 사용자 검색
    # ------------------------------------------------------------------
    def list_relations(
        self, viewer_id: int, target_id: int, kind: str, query: str = "", limit=30, offset=0
    ) -> dict:
        """target의 팔로워(kind='followers') 또는 팔로잉(kind='following') 목록을 돌려준다.

        목록은 상세를 볼 수 있는 사람에게만 보인다. 정지 계정과 viewer와 차단 관계인 사용자는 빼고,
        각 행에 viewer와의 관계를 담아 화면이 버튼(팔로우/요청됨/팔로잉)을 바로 그릴 수 있게 한다.

        Raises:
            FollowServiceError: 사용자가 없거나(404) 목록을 볼 수 없는 경우(403).
        """
        if kind not in ("followers", "following"):
            raise FollowServiceError("올바르지 않은 목록입니다.")
        limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        offset = max(0, int(offset))
        query = (query or "").strip().lower()[:50]
        with self._connection_factory() as conn:
            target = self._visible_user(conn, viewer_id, target_id)
            if not self.can_view_details(conn, viewer_id, target):
                raise FollowServiceError("비공개 계정입니다.", 403)
            # followers: 나(target)를 팔로우하는 사람 = follower_id 쪽 사용자. following는 반대.
            join_column, filter_column = (
                ("follower_id", "followee_id")
                if kind == "followers"
                else ("followee_id", "follower_id")
            )
            pattern = f"%{escape_like(query)}%"
            rows = conn.execute(
                f"""
                SELECT u.id, u.username, u.display_name, u.profile_image
                FROM follows f JOIN users u ON u.id = f.{join_column}
                WHERE f.{filter_column} = %s AND NOT u.is_suspended
                  AND NOT EXISTS (
                      SELECT 1 FROM blocks b
                      WHERE (b.blocker_id = %s AND b.blocked_id = u.id)
                         OR (b.blocker_id = u.id AND b.blocked_id = %s))
                  AND (%s = '' OR LOWER(u.username) LIKE %s ESCAPE '\\'
                       OR LOWER(COALESCE(u.display_name, '')) LIKE %s ESCAPE '\\')
                ORDER BY f.created_at DESC, u.id DESC
                LIMIT %s OFFSET %s
                """,
                (target_id, viewer_id, viewer_id, query, pattern, pattern, limit + 1, offset),
            ).fetchall()
            has_more = len(rows) > limit
            users = [self._user_with_relation(conn, viewer_id, row) for row in rows[:limit]]
        return {"users": users, "hasMore": has_more}

    def find_users(self, viewer_id: int, query: str, limit=20) -> list[dict]:
        """아이디나 이름의 일부로 사용자를 찾는다. 너무 짧은 검색어는 계정을 훑는 데 쓰일 수 있어 거부한다."""
        query = (query or "").strip().lower()[:50]
        if len(query) < MIN_SEARCH_LENGTH:
            raise FollowServiceError(f"{MIN_SEARCH_LENGTH}글자 이상 입력해주세요.")
        limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        pattern = f"%{escape_like(query)}%"
        with self._connection_factory() as conn:
            rows = conn.execute(
                """
                SELECT u.id, u.username, u.display_name, u.profile_image
                FROM users u
                WHERE u.id != %s AND NOT u.is_suspended
                  AND NOT EXISTS (
                      SELECT 1 FROM blocks b
                      WHERE (b.blocker_id = %s AND b.blocked_id = u.id)
                         OR (b.blocker_id = u.id AND b.blocked_id = %s))
                  AND (LOWER(u.username) LIKE %s ESCAPE '\\'
                       OR LOWER(COALESCE(u.display_name, '')) LIKE %s ESCAPE '\\')
                ORDER BY (LOWER(u.username) = %s) DESC, LENGTH(u.username), u.username
                LIMIT %s
                """,
                (viewer_id, viewer_id, viewer_id, pattern, pattern, query, limit),
            ).fetchall()
            return [self._user_with_relation(conn, viewer_id, row) for row in rows]

    def _user_with_relation(self, conn, viewer_id: int, row) -> dict:
        return {
            "id": row["id"],
            "username": row["username"],
            "displayName": row["display_name"] or row["username"],
            "profileImage": row["profile_image"],
            "relation": self.relation(conn, viewer_id, row["id"]),
        }

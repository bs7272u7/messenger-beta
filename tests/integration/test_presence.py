"""접속 상태 알림(broadcast_presence) 단위 테스트. 알림이 1:1 대화방 상대에게만 가는지 확인한다."""

import unittest
from unittest import mock

import app as application_module


class PresenceBroadcastTests(unittest.TestCase):
    """접속 상태 변화는 모든 접속자가 아니라 1:1 대화방 상대의 개인 방으로만 보낸다."""

    def test_notifies_only_one_to_one_peers(self):
        """대상 조회 결과(2, 5)에게만 이벤트가 가고, 내용은 사용자 ID와 접속 여부다."""
        notify = mock.Mock()

        with (
            mock.patch.object(application_module, "get_presence_audience", return_value=[2, 5]),
            mock.patch.object(application_module, "notify_user", notify),
        ):
            application_module.broadcast_presence(1, True)

        self.assertEqual(
            notify.call_args_list,
            [
                mock.call(2, "presence_updated", {"userId": 1, "online": True}),
                mock.call(5, "presence_updated", {"userId": 1, "online": True}),
            ],
        )

    def test_lookup_failure_does_not_break_the_connection(self):
        """대상 조회가 실패해도 예외를 밖으로 내보내지 않고 아무에게도 보내지 않는다."""
        notify = mock.Mock()

        with (
            mock.patch.object(
                application_module, "get_presence_audience", side_effect=RuntimeError("db down")
            ),
            mock.patch.object(application_module, "notify_user", notify),
        ):
            application_module.broadcast_presence(1, False)

        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()

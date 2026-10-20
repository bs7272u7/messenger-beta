"""서버 시작 시 DB 초기화 재시도(retry_init_db_in_background) 테스트."""

import unittest
from unittest import mock

import app as application_module


class InitDbRetryTests(unittest.TestCase):
    """DB가 늦게 준비돼도 서버를 재시작하지 않고 테이블이 만들어져야 한다."""

    def test_retries_until_init_db_succeeds(self):
        """두 번 실패한 뒤 세 번째에 성공하면 거기서 멈춘다. 대기 시간은 5초부터 두 배씩 늘어난다."""
        init_db = mock.Mock(
            side_effect=[ConnectionError("db down"), ConnectionError("db down"), None]
        )
        sleep = mock.Mock()

        with (
            mock.patch.object(application_module, "init_db", init_db),
            mock.patch.object(application_module.socketio, "sleep", sleep),
        ):
            application_module.retry_init_db_in_background()

        self.assertEqual(init_db.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10, 20])

    def test_retry_delay_is_capped_at_sixty_seconds(self):
        """실패가 길게 이어져도 대기 시간은 60초를 넘지 않는다."""
        init_db = mock.Mock(side_effect=[ConnectionError("db down")] * 6 + [None])
        sleep = mock.Mock()

        with (
            mock.patch.object(application_module, "init_db", init_db),
            mock.patch.object(application_module.socketio, "sleep", sleep),
        ):
            application_module.retry_init_db_in_background()

        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list], [5, 10, 20, 40, 60, 60, 60]
        )


if __name__ == "__main__":
    unittest.main()

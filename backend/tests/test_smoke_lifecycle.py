from unittest.mock import Mock

import httpx
import pytest

from backend.tests import smoke_http as smoke


def test_readiness_timeout_has_total_deadline_and_short_probe(monkeypatch, tmp_path):
    clock = [0.0]
    monkeypatch.setattr(smoke.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(smoke.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    server = Mock()
    server.poll.return_value = None
    client = Mock()

    def unreachable(*args, **kwargs):
        clock[0] += kwargs['timeout']
        raise httpx.ConnectTimeout('not ready')

    client.get.side_effect = unreachable
    with pytest.raises(RuntimeError, match='timed out after 1s'):
        smoke.wait_ready(client, server, tmp_path / 'server.log', timeout=1)
    assert clock[0] == pytest.approx(1)
    assert all(call.kwargs['timeout'] <= 0.5 for call in client.get.call_args_list)


@pytest.mark.parametrize('failure', [KeyboardInterrupt(), RuntimeError('readiness failed')])
def test_startup_failure_always_closes_client_and_process(monkeypatch, tmp_path, failure):
    server = Mock()
    server.poll.return_value = None
    monkeypatch.setattr(smoke.subprocess, 'Popen', Mock(return_value=server))
    client = Mock()
    manager = Mock()
    manager.__enter__ = Mock(return_value=client)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(smoke.httpx, 'Client', Mock(return_value=manager))
    monkeypatch.setattr(smoke, 'wait_ready', Mock(side_effect=failure))
    with pytest.raises(type(failure)):
        with smoke.running_server(tmp_path, {}, 8765, None):
            pytest.fail('Should never become ready')
    manager.__exit__.assert_called_once()
    server.terminate.assert_called_once()
    server.wait.assert_called_once_with(timeout=5)


def test_unresponsive_process_is_killed_after_bounded_wait():
    server = Mock()
    server.poll.return_value = None
    server.wait.side_effect = [smoke.subprocess.TimeoutExpired('server', 5), 0]
    smoke.stop_server(server)
    server.kill.assert_called_once()
    assert server.wait.call_count == 2

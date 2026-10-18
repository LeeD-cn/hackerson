"""Transport tests using httpx.MockTransport, never a shared backend."""
import json
import subprocess
import sys
from pathlib import Path

import anyio
import httpx
import pytest

from mcp_bridge.http_client import BackendError, ConfigurationError, RelayHTTPClient, Settings

ROOT = Path(__file__).resolve().parents[2]
TOKEN = 'simulation-only-credential'


def test_settings_normalize_origin_and_hide_token():
    settings = Settings.from_env({'RELAY_API_URL': 'http://127.0.0.1:8765/', 'RELAY_TASK_TOKEN': TOKEN})
    assert settings.api_url == 'http://127.0.0.1:8765'
    assert settings.timeout_seconds == 10
    assert TOKEN not in repr(settings)


@pytest.mark.parametrize('origin', [
    '', 'ftp://localhost', 'http://', 'http://localhost/api',
    'http://user:secret@localhost', 'http://localhost?key=secret',
    'http://localhost#secret', 'http://localhost?', 'http://localhost#',
    'http://localhost:invalid', 'http://localhost:99999',
    'http://local host', 'http://localhost/another/path',
])
def test_invalid_origin_errors_do_not_echo_configuration(origin):
    with pytest.raises(ConfigurationError) as caught:
        Settings.from_env({'RELAY_API_URL': origin, 'RELAY_TASK_TOKEN': TOKEN})
    assert TOKEN not in str(caught.value)
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('token', ['', 'a b', 'token\nsecret', '\u4e2d\u6587'])
def test_invalid_tokens_are_not_echoed(token):
    with pytest.raises(ConfigurationError) as caught:
        Settings.from_env({'RELAY_API_URL': 'http://localhost', 'RELAY_TASK_TOKEN': token})
    assert 'secret' not in str(caught.value)
    assert '\u4e2d\u6587' not in str(caught.value)


@pytest.mark.parametrize('timeout', ['0', '-1', '301', 'nan', 'inf', 'invalid', ''])
def test_invalid_timeout(timeout):
    with pytest.raises(ConfigurationError):
        Settings.from_env({'RELAY_API_URL': 'http://localhost', 'RELAY_TASK_TOKEN': TOKEN, 'RELAY_HTTP_TIMEOUT_SECONDS': timeout})


def invoke(response_or_error, *, action='update_my_context', arguments=None):
    calls = []

    def handler(request):
        calls.append(request)
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error

    async def run():
        async with RelayHTTPClient(Settings('http://relay.invalid', TOKEN), transport=httpx.MockTransport(handler)) as client:
            return await client.call(action, {'expected_version': 1} if arguments is None else arguments)

    return run, calls


def test_http_only_forwards_json_bearer_and_exact_route():
    run, calls = invoke(httpx.Response(200, json={'context': {'version': 2}}), arguments={'expected_version': 1, 'summary': None, 'todos': ''})
    assert anyio.run(run) == {'context': {'version': 2}}
    assert len(calls) == 1
    request = calls[0]
    assert request.method == 'POST'
    assert str(request.url) == 'http://relay.invalid/api/tools/update_my_context'
    assert request.headers['Authorization'] == f'Bearer {TOKEN}'
    assert request.headers['content-type'] == 'application/json'
    assert json.loads(request.content) == {'expected_version': 1, 'summary': None, 'todos': ''}
    assert 'task_id' not in json.loads(request.content)


@pytest.mark.parametrize(('status', 'code'), [(401, 'unauthorized'), (403, 'forbidden'), (409, 'version_conflict'), (422, 'invalid_input'), (500, 'internal_error')])
def test_backend_error_shape_is_preserved_and_redacted_without_retry(status, code):
    backend_error = {'code': code, 'message': 'Example actionable backend reason ' + TOKEN, 'details': [{'field': 'summary', 'message': TOKEN}], 'private_debug': 'must not forward'}
    run, calls = invoke(httpx.Response(status, json={'error': backend_error}))
    with pytest.raises(BackendError) as caught:
        anyio.run(run)
    error = caught.value.error
    assert error['code'] == code
    assert error['message'] == 'Example actionable backend reason [REDACTED]'
    assert error['details'] == [{'field': 'summary', 'message': '[REDACTED]'}]
    assert 'private_debug' not in error
    assert TOKEN not in json.dumps(error)
    assert len(calls) == 1


@pytest.mark.parametrize(('status', 'code'), [(401, 'unauthorized'), (403, 'forbidden'), (404, 'not_found'), (409, 'version_conflict'), (422, 'invalid_input'), (500, 'backend_http_error'), (302, 'backend_http_error')])
def test_non_contract_errors_and_redirects_are_safe(status, code):
    run, calls = invoke(httpx.Response(status, text='<html>' + TOKEN, headers={'location': 'https://other.invalid'}))
    with pytest.raises(BackendError) as caught:
        anyio.run(run)
    assert caught.value.error['code'] == code
    assert TOKEN not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize(('failure', 'code'), [
    (httpx.ConnectError(TOKEN), 'backend_unreachable'),
    (httpx.RemoteProtocolError(TOKEN), 'backend_unreachable'),
    (httpx.ConnectTimeout(TOKEN), 'backend_timeout'),
    (httpx.ReadTimeout(TOKEN), 'backend_timeout'),
    (httpx.WriteTimeout(TOKEN), 'backend_timeout'),
    (httpx.PoolTimeout(TOKEN), 'backend_timeout'),
])
def test_network_errors_are_actionable_without_exception_or_retry(failure, code):
    run, calls = invoke(failure)
    with pytest.raises(BackendError) as caught:
        anyio.run(run)
    assert caught.value.error['code'] == code
    assert TOKEN not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize('response', [httpx.Response(200, text='not json ' + TOKEN), httpx.Response(200, json=[]), httpx.Response(200, json=None)])
def test_invalid_success_responses(response):
    run, calls = invoke(response)
    with pytest.raises(BackendError) as caught:
        anyio.run(run)
    assert caught.value.error['code'] == 'invalid_backend_response'
    assert TOKEN not in str(caught.value)
    assert len(calls) == 1


def test_config_failure_exits_cleanly_without_protocol_stdout(tmp_path, monkeypatch):
    monkeypatch.delenv('RELAY_API_URL', raising=False)
    monkeypatch.setenv('RELAY_TASK_TOKEN', TOKEN)
    process = subprocess.run([sys.executable, '-B', str(ROOT / 'mcp_bridge/server.py')], cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert process.returncode == 2
    assert process.stdout == ''
    assert 'RELAY_API_URL is required' in process.stderr
    assert TOKEN not in process.stderr

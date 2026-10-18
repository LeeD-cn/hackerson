"""Real TCP/startup/restart smoke test; all artifacts remain under .tmp/."""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]


def stop_server(server):
    if server.poll() is None:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def wait_ready(client, server, log_path, timeout=15):
    deadline = time.monotonic() + timeout
    last_error = 'No health response'
    while True:
        if server.poll() is not None:
            raise RuntimeError(f'Server exited; see {log_path}')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f'Server readiness timed out after {timeout}s ({last_error}); see {log_path}')
        try:
            response = client.get('/health', timeout=min(0.5, remaining), headers={'Connection': 'close'})
            if response.status_code == 200:
                return
            last_error = f'HTTP {response.status_code}'
        except httpx.TransportError as exc:
            last_error = type(exc).__name__
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


@contextmanager
def running_server(run_dir, env, port, log):
    server = subprocess.Popen([sys.executable, '-m', 'backend', '--port', str(port),
                               '--db', str(run_dir / 'relay.db')], cwd=ROOT, env=env,
                              stdout=log, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        # A restarted process gets a fresh client/pool; no sockets survive the restart.
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=3) as client:
            wait_ready(client, server, run_dir / 'server.log')
            yield client
    finally:
        # Includes KeyboardInterrupt during readiness, before control reaches the caller.
        stop_server(server)


def main():
    run_dir = ROOT / '.tmp' / f'backend-http-{uuid4().hex}'
    run_dir.mkdir(parents=True)
    admin = secrets.token_urlsafe(32)
    env = {**os.environ, 'RELAY_ADMIN_TOKEN': admin, 'PYTHONUTF8': '1'}
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]

    def call(client, action, token=admin, **arguments):
        response = client.post(f'/api/tools/{action}', json=arguments,
                               headers={'Authorization': f'Bearer {token}'})
        response.raise_for_status()
        return response.json()

    print(f'Test artifacts: {run_dir}', flush=True)
    with (run_dir / 'server.log').open('w', encoding='utf-8') as log:
        print('[1/3] Starting HTTP server (readiness deadline: 15s)...', flush=True)
        with running_server(run_dir, env, port, log) as client:
            print('[2/3] Checking tasks, context, query and approval...', flush=True)
            api_task = call(client, 'create_task', name='报名接口', goal='提供报名服务', contract='POST /registrations: {name}')['task']
            form = call(client, 'create_task', name='报名表单', goal='提交报名', dependencies=[api_task['task_id']])['task']
            token = call(client, 'issue_task_token', task_id=form['task_id'])['token']
            context = call(client, 'get_my_context', token)
            call(client, 'update_my_context', token, expected_version=context['context']['version'], next_steps='继续接入接口')
            assert call(client, 'query_module', token, task_id=api_task['task_id'])['contract']['contract'].startswith('POST')
            proposal = call(client, 'propose_change', token, task_id=api_task['task_id'], title='增加学号', rationale='避免重复报名',
                            expected_project_version=context['project_version'], patch={'contract': 'POST /registrations: {name, student_id}'})
            approved = call(client, 'review_change', change_id=proposal['change_id'], approve=True, note='采用新接口')
            assert set(approved['affected_tasks']) == {api_task['task_id'], form['task_id']}
        print('[3/3] Restarting server and checking persistence (readiness deadline: 15s)...', flush=True)
        with running_server(run_dir, env, port, log) as client:
            restored = call(client, 'get_my_context', token)
            assert restored['context']['data']['next_steps'] == '继续接入接口'
            assert 'student_id' in restored['dependency_contracts'][0]['contract']
            assert any(n['decision_id'] == approved['decision_id'] for n in restored['notifications'])
    print(json.dumps({'http': 'passed', 'restart_persistence': 'passed', 'approval_notifications': 'passed',
                      'artifacts': str(run_dir)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nTest cancelled; its server process has been stopped.', file=sys.stderr)
        sys.exit(130)
    except (RuntimeError, httpx.HTTPError) as exc:
        print(f'Test failed: {exc}', file=sys.stderr)
        sys.exit(1)

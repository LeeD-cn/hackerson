"""Real TCP/startup/restart smoke test; all artifacts remain under .tmp/."""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    run_dir = ROOT / '.tmp' / f'backend-http-{uuid4().hex}'
    run_dir.mkdir(parents=True)
    admin = secrets.token_urlsafe(32)
    env = {**os.environ, 'RELAY_ADMIN_TOKEN': admin, 'PYTHONUTF8': '1'}
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    client = httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=3)
    log = (run_dir / 'server.log').open('w', encoding='utf-8')
    process = None

    def start():
        server = subprocess.Popen([sys.executable, '-m', 'backend', '--port', str(port),
                                   '--db', str(run_dir / 'relay.db')], cwd=ROOT, env=env,
                                  stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError(f'Server exited; see {run_dir / "server.log"}')
            try:
                if client.get('/health').status_code == 200:
                    return server
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        server.terminate()
        server.wait(timeout=10)
        raise RuntimeError('Server startup timed out')

    def call(action, token=admin, **arguments):
        response = client.post(f'/api/tools/{action}', json=arguments,
                               headers={'Authorization': f'Bearer {token}'})
        response.raise_for_status()
        return response.json()

    try:
        process = start()
        api_task = call('create_task', name='报名接口', goal='提供报名服务', contract='POST /registrations: {name}')['task']
        form = call('create_task', name='报名表单', goal='提交报名', dependencies=[api_task['task_id']])['task']
        token = call('issue_task_token', task_id=form['task_id'])['token']
        context = call('get_my_context', token)
        call('update_my_context', token, expected_version=context['context']['version'], next_steps='继续接入接口')
        assert call('query_module', token, task_id=api_task['task_id'])['contract']['contract'].startswith('POST')
        proposal = call('propose_change', token, task_id=api_task['task_id'], title='增加学号', rationale='避免重复报名',
                        expected_project_version=context['project_version'], patch={'contract': 'POST /registrations: {name, student_id}'})
        approved = call('review_change', change_id=proposal['change_id'], approve=True, note='采用新接口')
        assert set(approved['affected_tasks']) == {api_task['task_id'], form['task_id']}
        process.terminate()
        process.wait(timeout=10)
        process = start()
        restored = call('get_my_context', token)
        assert restored['context']['data']['next_steps'] == '继续接入接口'
        assert 'student_id' in restored['dependency_contracts'][0]['contract']
        assert any(n['decision_id'] == approved['decision_id'] for n in restored['notifications'])
        print(json.dumps({'http': 'passed', 'restart_persistence': 'passed', 'approval_notifications': 'passed',
                          'artifacts': str(run_dir)}, ensure_ascii=False))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        client.close()
        log.close()


if __name__ == '__main__':
    main()

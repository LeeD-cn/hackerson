"""Run BE-02 over real HTTP, then restart and verify both saved contexts."""
import json
import os
import secrets
import socket
from uuid import uuid4

from backend import be02
from backend.tests.smoke_http import running_server


def main():
    run_dir = be02.ROOT / '.local' / 'be02' / f'run-{uuid4().hex[:12]}'
    run_dir.mkdir(parents=True)
    admin = secrets.token_urlsafe(32)
    (run_dir / 'admin-token.txt').write_text(admin, encoding='utf-8')
    env = {**os.environ, 'RELAY_ADMIN_TOKEN': admin, 'PYTHONUTF8': '1'}
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    credentials = run_dir / 'credentials.json'
    print(f'Local fixture files: {run_dir}', flush=True)
    with (run_dir / 'server.log').open('w', encoding='utf-8') as log:
        print('[1/3] Start and seed two task identities...', flush=True)
        with running_server(run_dir, env, port, log) as client:
            bundle = be02.seed(client, admin, credentials)
            print('[2/3] Check types, isolation, update semantics and errors...', flush=True)
            report = be02.check(client, bundle, credentials)
        print('[3/3] Restart and restore both identities...', flush=True)
        with running_server(run_dir, env, port, log) as client:
            be02.verify_restored(client, json.loads(credentials.read_text(encoding='utf-8')))
    print(json.dumps({'be02_http': 'passed', 'restart_persistence': 'passed',
                      'credentials_file': str(credentials), 'redacted_report': str(report)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()

"""Seed and exercise the BE-02 HTTP integration fixture without printing credentials."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from contracts.responses import BootstrapContext, ErrorResponse, QueryModuleResponse, TaskContext

ROOT = Path(__file__).resolve().parents[1]


def local_path(path):
    resolved = Path(path).resolve()
    if not any(resolved.is_relative_to(ROOT / folder) for folder in ('.local', '.tmp')):
        raise ValueError('Credentials/reports must stay inside the ignored project .local/ or .tmp/ directory')
    return resolved


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def request(client, action, token, arguments=None, expected=200, trace=None, identity='task'):
    arguments = {} if arguments is None else arguments
    response = client.post(f'/api/tools/{action}', json=arguments, headers={'Authorization': f'Bearer {token}'})
    if response.status_code != expected:
        # Do not echo headers, token-issuing responses or request data on failure.
        raise RuntimeError(f'{action}: expected HTTP {expected}, received {response.status_code}')
    data = response.json()
    if expected >= 400:
        ErrorResponse.model_validate(data)
    if trace is not None:
        trace.append({'method': 'POST', 'path': f'/api/tools/{action}', 'identity': identity,
                      'request': arguments, 'status': response.status_code, 'response': data})
    return data


def seed(client, admin, credentials_path):
    path = local_path(credentials_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Fail before creating remote data if this fixture already exists; never rotate a teammate's token.
    with path.open('x', encoding='utf-8') as stream:
        stream.write('{}')
    bundle = {'base_url': str(client.base_url).rstrip('/'), 'initialized': False, 'tasks': {}}
    save(path, bundle)
    suffix = uuid4().hex[:12]
    for alias in ('b', 'a'):
        dependencies = [] if alias == 'b' else [bundle['tasks']['b']['task_id']]
        task = request(client, 'create_task', admin, {
            'name': f'BE02-{alias.upper()}-{suffix}', 'goal': f'BE-02 local integration task {alias.upper()}',
            'dependencies': dependencies,
            'contract': f'PUBLIC_{alias.upper()}: GET /be02/{alias} returns {{"ok":true}}',
        })['task']
        token = request(client, 'issue_task_token', admin, {'task_id': task['task_id']})['token']
        bundle['tasks'][alias] = {'task_id': task['task_id'], 'token': token,
                                  'private_marker': f'BE02_PRIVATE_{alias.upper()}_{suffix}'}
        save(path, bundle)
        context = request(client, 'update_my_context', token, {
            'expected_version': 1, 'summary': bundle['tasks'][alias]['private_marker'],
            'todos': f'Private todo {alias.upper()}', 'next_steps': 'Read the published dependency contract',
        })
        bundle['tasks'][alias]['expected_context'] = context
        save(path, bundle)
    # Keep a deliberately revoked token for reproducible 401 checks.
    bundle['revoked_a_token'] = bundle['tasks']['a']['token']
    save(path, bundle)
    bundle['tasks']['a']['token'] = request(client, 'issue_task_token', admin, {'task_id': bundle['tasks']['a']['task_id']})['token']
    bundle['initialized'] = True
    save(path, bundle)
    return bundle


def check(client, bundle, credentials_path):
    trace, expected_contexts = [], {}
    for alias, other in [('a', 'b'), ('b', 'a')]:
        own = bundle['tasks'][alias]
        value = request(client, 'get_my_context', own['token'], trace=trace, identity=alias)
        BootstrapContext.model_validate(value)
        assert value['task']['task_id'] == own['task_id']
        assert value['context']['data']['summary'] == own['private_marker']
        assert bundle['tasks'][other]['private_marker'] not in json.dumps(value)
        expected_contexts[alias] = value['context']
    a, b = bundle['tasks']['a'], bundle['tasks']['b']
    before = expected_contexts['a']
    version = before['version']
    # Same-value write is deliberate: this must still create exactly one new version.
    updated = request(client, 'update_my_context', a['token'], {
        'expected_version': version, 'summary': None, 'todos': '',
        'next_steps': before['data']['next_steps'],
    }, trace=trace, identity='a')
    TaskContext.model_validate(updated)
    assert updated['version'] == version + 1
    assert updated['data']['summary'] == before['data']['summary']
    assert updated['data']['todos'] == ''
    identical = request(client, 'update_my_context', a['token'], {
        'expected_version': updated['version'], 'next_steps': updated['data']['next_steps'],
    }, trace=trace, identity='a')
    assert identical['version'] == updated['version'] + 1 and identical['data'] == updated['data']
    for arguments, status, error_code in [
        ({'expected_version': version, 'summary': 'stale value'}, 409, 'version_conflict'),
        ({'expected_version': identical['version']}, 422, 'invalid_input'),
        ({'expected_version': identical['version'], 'summary': None}, 422, 'invalid_input'),
        ({}, 422, 'invalid_input'),
    ]:
        error = request(client, 'update_my_context', a['token'], arguments, status, trace, 'a')
        assert error['error']['code'] == error_code
        assert request(client, 'get_my_context', a['token'])['context'] == identical
    query = request(client, 'query_module', a['token'], {'task_id': b['task_id'], 'question': 'Published contract only'}, trace=trace, identity='a')
    QueryModuleResponse.model_validate(query)
    assert set(query['contract']) == {'task_id', 'name', 'contract', 'version'}
    assert all(item['private_marker'] not in json.dumps(query) for item in bundle['tasks'].values())
    for action, token, arguments, status, code in [
        ('get_my_context', bundle['revoked_a_token'], {}, 401, 'unauthorized'),
        ('get_task_context', a['token'], {'task_id': b['task_id']}, 403, 'forbidden'),
        ('query_module', a['token'], {'task_id': 'be02_missing_task'}, 404, 'task_not_found'),
        ('be02_unimplemented_action', a['token'], {}, 404, 'unknown_tool'),
    ]:
        assert request(client, action, token, arguments, status, trace, 'a/revoked' if status == 401 else 'a')['error']['code'] == code
    expected_contexts['a'] = identical
    # Verify both accounts after mutations, including that B did not change.
    for alias, context in expected_contexts.items():
        assert request(client, 'get_my_context', bundle['tasks'][alias]['token'])['context'] == context
        bundle['tasks'][alias]['expected_context'] = context
    path = local_path(credentials_path)
    save(path, bundle)
    report = path.with_name(path.stem + '-report.json')
    save(report, {'result': 'passed', 'requests': trace})
    # Trace identities are aliases; neither credentials nor Authorization headers are included.
    assert all(item['token'] not in report.read_text(encoding='utf-8') for item in bundle['tasks'].values())
    return report


def verify_restored(client, bundle):
    for item in bundle['tasks'].values():
        actual = request(client, 'get_my_context', item['token'])
        assert actual['context'] == item['expected_context']


def main():
    parser = argparse.ArgumentParser(description='BE-02 local HTTP integration fixture')
    parser.add_argument('command', choices=['seed', 'check', 'verify-restored'])
    parser.add_argument('--url', help='Default: saved fixture URL or http://127.0.0.1:8765')
    parser.add_argument('--credentials', type=Path, default=ROOT / '.local/be02/credentials.json')
    parser.add_argument('--admin-token-file', type=Path, default=ROOT / '.local/admin-token.txt')
    args = parser.parse_args()
    path = local_path(args.credentials)
    bundle = None if args.command == 'seed' else json.loads(path.read_text(encoding='utf-8'))
    if bundle is not None and not bundle.get('initialized'):
        raise RuntimeError('Fixture initialization did not finish; seed again with a new credentials filename')
    url = args.url or (bundle['base_url'] if bundle else 'http://127.0.0.1:8765')
    with httpx.Client(base_url=url, timeout=5, trust_env=False) as client:
        client.get('/health').raise_for_status()
        if args.command == 'seed':
            admin = os.environ.get('RELAY_ADMIN_TOKEN') or args.admin_token_file.read_text(encoding='utf-8').strip()
            seed(client, admin, path)
            print(f'Two tasks and separate tokens saved locally: {path}')
        elif args.command == 'check':
            report = check(client, bundle, path)
            print(f'BE-02 checks passed. Redacted request/response report: {report}')
        else:
            verify_restored(client, bundle)
            print('Both task contexts match the saved checkpoint.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, AssertionError, httpx.HTTPError) as exc:
        raise SystemExit(f'BE-02 failed ({type(exc).__name__}); check server availability, local fixture files and versions. '
                         'Existing fixture files are never reset by seed. Use a new --credentials path for another fixture.') from None

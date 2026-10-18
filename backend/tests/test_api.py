import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from contracts.responses import BootstrapContext, Notification, Snapshot


ADMIN = 'test-administrator-token-at-least-24-chars'


@pytest.fixture
def api(tmp_path):
    app = create_app(tmp_path / 'relay.db', ADMIN)
    with TestClient(app) as client:
        yield client


def call(api, action, token=ADMIN, code=200, **arguments):
    response = api.post(f'/api/tools/{action}', json=arguments,
                        headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == code, response.text
    return response.json()


def task(api, name='Example', **fields):
    return call(api, 'create_task', name=name, goal=f'Goal of {name}', **fields)['task']


def credential(api, task):
    return call(api, 'issue_task_token', task_id=task['task_id'])['token']


def complete_notifications(api, token):
    for notification in call(api, 'get_notifications', token)['notifications']:
        for status in ['acknowledged', 'completed']:
            call(api, 'acknowledge_change', token, notification_id=notification['id'], status=status, note='Handled')


def test_health_schemas_and_uniform_errors(api):
    assert api.get('/health').json() == {'status': 'ok', 'version': '0.1.0'}
    assert 'get_my_context' in api.get('/api/tool-schemas').json()
    assert call(api, 'snapshot', '', 401)['error']['code'] == 'unauthorized'
    assert call(api, 'snapshot', 'invalid-token', 401)['error']['code'] == 'unauthorized'
    assert call(api, 'missing', code=404)['error']['code'] == 'unknown_tool'
    assert call(api, 'create_task', code=422, name='No goal')['error']['code'] == 'invalid_input'
    for body in ['[1,2]', '{broken', 'null']:
        response = api.post('/api/tools/create_task', content=body, headers={'Content-Type': 'application/json'})
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'invalid_input'
    assert api.get('/missing').json()['error']['code'] == 'not_found'


def test_two_tasks_private_context_and_master_boundaries(api):
    a = task(api, 'A')
    b = task(api, 'B', contract='public API', description='private-description-B')
    at, bt = credential(api, a), credential(api, b)
    call(api, 'update_my_context', bt, expected_version=1, summary='private-work-B')
    version = call(api, 'list_tasks', at)['project_version']
    call(api, 'edit_project', expected_version=version, name='Project', private_context='global-secret',
         guidance='safe guidance', reason='internal-reason')
    bootstrap = call(api, 'get_my_context', at)
    BootstrapContext.model_validate(bootstrap)
    assert bootstrap['guidance'] == 'safe guidance'
    assert bootstrap['task']['task_id'] == a['task_id']
    for secret in ['global-secret', 'internal-reason', 'private-work-B', 'private-description-B']:
        assert secret not in str(bootstrap)
        assert secret not in str(call(api, 'list_tasks', at))
    query = call(api, 'query_module', at, task_id=b['task_id'], question='What is the API?')
    assert set(query['contract']) == {'task_id', 'name', 'contract', 'version'}
    assert query['contract']['contract'] == 'public API'
    for operation, args in [('snapshot', {}), ('get_project_context', {}),
                            ('get_task_context', {'task_id': b['task_id']}),
                            ('issue_task_token', {'task_id': b['task_id']}),
                            ('create_task', {'name': 'bad', 'goal': 'bad'})]:
        assert call(api, operation, at, 403, **args)['error']['code'] == 'forbidden'
    call(api, 'update_my_context', at, 422, expected_version=1, summary='bad', task_id=b['task_id'])
    for role in ['coordinator', 'reviewer']:
        rt = call(api, 'issue_role_token', role=role)['token']
        Snapshot.model_validate(call(api, 'snapshot', rt))
        assert call(api, 'get_task_context', rt, task_id=b['task_id'])['context']['data']['summary'] == 'private-work-B'
        call(api, 'create_task', rt, 403, name='bad', goal='bad')
        call(api, 'review_change', rt, 403, change_id='missing', approve=True, note='bad')


def test_context_optimistic_lock_history_and_restart(api):
    a = task(api)
    token = credential(api, a)
    first = call(api, 'get_my_context', token)
    result = call(api, 'update_my_context', token, expected_version=1, summary='persist me', next_steps='continue here')
    assert result['version'] == 2
    call(api, 'update_my_context', token, 409, expected_version=1, summary='overwrite')
    call(api, 'update_my_context', token, 422, expected_version=2)
    current = call(api, 'get_my_context', token)
    assert current['project_version'] == first['project_version']
    assert current['task']['version'] == first['task']['version']
    with sqlite3.connect(api.app.state.store.path) as db:
        assert db.execute('SELECT count(*) FROM context_history').fetchone()[0] == 2
    with TestClient(create_app(api.app.state.store.path, ADMIN)) as restarted:
        restored = call(restarted, 'get_my_context', token)
        assert restored['context']['data']['summary'] == 'persist me'
        assert restored['context']['data']['next_steps'] == 'continue here'


def test_concurrent_context_update_has_one_winner(api):
    a = task(api)
    token = credential(api, a)

    def update(value):
        return api.post('/api/tools/update_my_context', json={'expected_version': 1, 'summary': value},
                        headers={'Authorization': f'Bearer {token}'}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(update, ['one', 'two']))
    assert sorted(statuses) == [200, 409]
    assert call(api, 'get_my_context', token)['context']['version'] == 2


def test_token_rotation_revokes_old_identity(api):
    a = task(api)
    old, new = credential(api, a), credential(api, a)
    call(api, 'get_my_context', old, 401)
    call(api, 'get_my_context', new)
    with sqlite3.connect(api.app.state.store.path) as db:
        records = db.execute('SELECT token_hash,revoked FROM credentials').fetchall()
        assert all(len(row[0]) == 64 and row[0] not in {old, new} for row in records)
        assert sum(row[1] for row in records) == 1


def test_dependency_and_parent_cycles_rollback(api):
    a = task(api, 'A')
    b = task(api, 'B', dependencies=[a['task_id']], parent_id=a['task_id'])
    before = call(api, 'snapshot')
    for patch, error in [({'dependencies': [b['task_id']]}, 'dependency_cycle'),
                         ({'parent_id': b['task_id']}, 'parent_cycle'),
                         ({'dependencies': [a['task_id']]}, 'dependency_cycle')]:
        result = call(api, 'edit_task', code=422, task_id=a['task_id'], expected_version=1, patch=patch, reason='bad graph')
        assert result['error']['code'] == error
    call(api, 'create_task', code=422, name='duplicate', goal='bad', dependencies=[a['task_id'], a['task_id']])
    call(api, 'create_task', code=404, name='missing', goal='bad', dependencies=['missing'])
    assert call(api, 'snapshot') == before


def test_approval_atomic_targeted_notifications_and_privacy(api):
    b = task(api, 'API', contract='v1')
    a = task(api, 'Form', dependencies=[b['task_id']])
    c = task(api, 'Child', parent_id=a['task_id'])
    unrelated = task(api, 'Unrelated')
    bt, at, ut = credential(api, b), credential(api, a), credential(api, unrelated)
    version = call(api, 'list_tasks', bt)['project_version']
    proposal = call(api, 'propose_change', bt, task_id=b['task_id'], title='API v2', rationale='needs update',
                    expected_project_version=version, patch={'contract': 'v2', 'description': 'private-new-description'})
    assert call(api, 'query_module', at, task_id=b['task_id'])['contract']['contract'] == 'v1'
    assert call(api, 'list_tasks', at)['project_version'] == version
    call(api, 'review_change', bt, 403, change_id=proposal['change_id'], approve=True, note='not allowed')
    result = call(api, 'review_change', change_id=proposal['change_id'], approve=True, note='internal-approval-note')
    assert set(result['affected_tasks']) == {a['task_id'], b['task_id'], c['task_id']}
    assert result['project_version'] == version + 1
    before = call(api, 'snapshot')
    call(api, 'review_change', code=409, change_id=proposal['change_id'], approve=True, note='duplicate')
    assert call(api, 'snapshot') == before
    bootstrap = call(api, 'get_my_context', at)
    assert bootstrap['dependency_contracts'][0]['contract'] == 'v2'
    assert 'private-new-description' not in str(bootstrap)
    assert 'internal-approval-note' not in str(bootstrap)
    assert len([n for n in bootstrap['notifications'] if n['project_version'] == version + 1]) == 1
    assert all(n['project_version'] != version + 1 for n in call(api, 'get_notifications', ut)['notifications'])
    assert call(api, 'list_changes', ut)['changes'] == []


def test_stale_proposal_and_rejection(api):
    a = task(api)
    token = credential(api, a)
    version = call(api, 'list_tasks', token)['project_version']
    proposal = call(api, 'propose_change', token, task_id=a['task_id'], title='change', rationale='why',
                    expected_project_version=version, patch={'contract': 'new'})
    call(api, 'edit_task', task_id=a['task_id'], expected_version=1, patch={'name': 'Renamed'}, reason='direct edit')
    before = call(api, 'snapshot')
    call(api, 'review_change', code=409, change_id=proposal['change_id'], approve=True, note='stale')
    assert call(api, 'snapshot') == before
    call(api, 'review_change', change_id=proposal['change_id'], approve=False, note='Resubmit against latest version')
    after = call(api, 'snapshot')
    assert after['project']['version'] == before['project']['version']
    assert after['notifications'] == before['notifications']
    assert after['changes'][0]['status'] == 'rejected'


def test_failure_mid_approval_rolls_back_everything(api, monkeypatch):
    a = task(api)
    token = credential(api, a)
    proposal = call(api, 'propose_change', token, task_id=a['task_id'], title='change', rationale='why',
                    expected_project_version=2, patch={'contract': 'new'})
    before = call(api, 'snapshot')
    store = api.app.state.store
    original = store.record_decision

    def fail_after_writes(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('simulated failure')

    monkeypatch.setattr(store, 'record_decision', fail_after_writes)
    call(api, 'review_change', code=500, change_id=proposal['change_id'], approve=True, note='approve')
    assert call(api, 'snapshot') == before


def test_notification_state_order_ownership_and_done_gate(api):
    a, b = task(api, 'A'), task(api, 'B')
    at, bt = credential(api, a), credential(api, b)
    notification = call(api, 'get_notifications', at)['notifications'][0]
    call(api, 'acknowledge_change', bt, 404, notification_id=notification['id'], status='acknowledged', note='bad')
    call(api, 'acknowledge_change', at, 409, notification_id=notification['id'], status='completed', note='skip')
    call(api, 'report_status', at, 409, expected_version=1, status='done', progress=100)
    for status in ['acknowledged', 'completed']:
        result = call(api, 'acknowledge_change', at, notification_id=notification['id'], status=status, note='Handled')
        Notification.model_validate(result)
        assert result['status'] == status
    assert call(api, 'acknowledge_change', at, notification_id=notification['id'], status='completed', note='retry') == result
    call(api, 'acknowledge_change', at, 409, notification_id=notification['id'], status='acknowledged', note='regress')
    call(api, 'report_status', at, expected_version=1, status='done', progress=100)
    call(api, 'report_status', at, 409, expected_version=1, status='in_progress', progress=50)


def test_message_visibility_and_reply_reference(api):
    a, b, c = task(api, 'A'), task(api, 'B'), task(api, 'C')
    at, bt, ct = credential(api, a), credential(api, b), credential(api, c)
    message = call(api, 'send_message', at, target=b['task_id'], body='shared only with B')
    assert message['sender'] == a['task_id']
    assert call(api, 'get_messages', bt)['messages'][0]['id'] == message['id']
    assert call(api, 'get_messages', ct)['messages'] == []
    call(api, 'send_message', ct, 404, target=a['task_id'], body='bad', reply_to=message['id'])
    call(api, 'send_message', bt, target=a['task_id'], body='reply', reply_to=message['id'])
    call(api, 'send_message', at, 422, target=b['task_id'], body='bad', sender=c['task_id'])


def test_archive_revokes_token_and_repairs_edges_without_erasing_history(api):
    a = task(api, 'A')
    b = task(api, 'B', dependencies=[a['task_id']], parent_id=a['task_id'])
    at, bt = credential(api, a), credential(api, b)
    call(api, 'update_my_context', at, expected_version=1, summary='retain after archive')
    result = call(api, 'delete_task', task_id=a['task_id'], expected_version=1, reason='internal archive reason')
    assert result['affected_tasks'] == [b['task_id']]
    call(api, 'get_my_context', at, 401)
    call(api, 'get_task_status', bt, 404, task_id=a['task_id'])
    bootstrap = call(api, 'get_my_context', bt)
    assert bootstrap['task']['parent_id'] is None
    assert bootstrap['task']['dependencies'] == []
    assert bootstrap['task']['version'] == 2
    assert 'internal archive reason' not in str(bootstrap)
    with sqlite3.connect(api.app.state.store.path) as db:
        assert db.execute('SELECT count(*) FROM context_history WHERE task_id=?', (a['task_id'],)).fetchone()[0] == 2
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []

import json
import sqlite3

import pytest

from backend.tests.test_api import api, call, credential, task
from contracts.responses import BootstrapContext, ErrorResponse, QueryModuleResponse, TaskContext


def history(api, task_id):
    with sqlite3.connect(api.app.state.store.path) as db:
        return db.execute('SELECT version,data FROM context_history WHERE task_id=? ORDER BY version', (task_id,)).fetchall()


def test_omitted_null_empty_and_identical_values(api):
    a = task(api)
    token = credential(api, a)
    initial = call(api, 'update_my_context', token, expected_version=1, summary='Keep', todos='To do')
    updated = call(api, 'update_my_context', token, expected_version=2, summary=None, todos='')
    TaskContext.model_validate(updated)
    assert updated['data']['summary'] == 'Keep'  # Explicit null ignored.
    assert updated['data']['todos'] == ''       # Empty string clears.
    assert updated['data']['next_steps'] == initial['data']['next_steps']  # Omitted remains.
    assert updated['version'] == 3
    same = call(api, 'update_my_context', token, expected_version=3, summary='Keep')
    assert same['version'] == 4
    assert same['data'] == updated['data']
    rows = history(api, a['task_id'])
    assert [row[0] for row in rows] == [1, 2, 3, 4]
    assert json.loads(rows[-1][1]) == same['data']


@pytest.mark.parametrize('arguments,status,code', [
    ({}, 422, 'invalid_input'),
    ({'expected_version': 2}, 422, 'invalid_input'),
    ({'expected_version': 2, 'summary': None, 'todos': None}, 422, 'invalid_input'),
    ({'expected_version': 1, 'summary': 'stale'}, 409, 'version_conflict'),
    ({'expected_version': 1, 'summary': None}, 409, 'version_conflict'),
])
def test_rejected_update_preserves_current_data_and_history(api, arguments, status, code):
    a = task(api)
    token = credential(api, a)
    before = call(api, 'update_my_context', token, expected_version=1, summary='Original')
    old_history = history(api, a['task_id'])
    error = ErrorResponse.model_validate(call(api, 'update_my_context', token, status, **arguments))
    assert error.error.code == code
    assert call(api, 'get_my_context', token)['context'] == before
    assert history(api, a['task_id']) == old_history


def test_context_and_history_are_atomic_on_insert_failure(api):
    a = task(api)
    token = credential(api, a)
    before = call(api, 'get_my_context', token)['context']
    old_history = history(api, a['task_id'])
    with sqlite3.connect(api.app.state.store.path) as db:
        db.execute("""CREATE TRIGGER simulate_history_failure BEFORE INSERT ON context_history
                      BEGIN SELECT RAISE(ABORT, 'simulated history write failure'); END""")
    error = call(api, 'update_my_context', token, 500, expected_version=1, summary='Must roll back')
    ErrorResponse.model_validate(error)
    assert call(api, 'get_my_context', token)['context'] == before
    assert history(api, a['task_id']) == old_history


def test_three_interfaces_use_shared_types_and_do_not_leak(api):
    b = task(api, 'API', contract='PUBLIC_B')
    a = task(api, 'Consumer', dependencies=[b['task_id']])
    at, bt = credential(api, a), credential(api, b)
    call(api, 'update_my_context', at, expected_version=1, summary='PRIVATE_A')
    call(api, 'update_my_context', bt, expected_version=1, summary='PRIVATE_B')
    for token, own, forbidden in [(at, 'PRIVATE_A', 'PRIVATE_B'), (bt, 'PRIVATE_B', 'PRIVATE_A')]:
        bootstrap = call(api, 'get_my_context', token)
        BootstrapContext.model_validate(bootstrap)
        assert bootstrap['context']['data']['summary'] == own
        assert forbidden not in json.dumps(bootstrap)
    result = call(api, 'query_module', at, task_id=b['task_id'], question='Only published contract')
    QueryModuleResponse.model_validate(result)
    assert result['contract']['contract'] == 'PUBLIC_B'
    assert all(secret not in json.dumps(result) for secret in ['PRIVATE_A', 'PRIVATE_B'])
    for action, token, arguments, status in [
        ('get_my_context', 'invalid', {}, 401),
        ('get_my_context', at, {'task_id': b['task_id']}, 422),
        ('get_task_context', at, {'task_id': b['task_id']}, 403),
        ('query_module', at, {'task_id': 'missing'}, 404),
        ('unimplemented_be02_example', at, {}, 404),
    ]:
        error = call(api, action, token, status, **arguments)
        ErrorResponse.model_validate(error)
        assert all(secret not in json.dumps(error) for secret in ['PRIVATE_A', 'PRIVATE_B'])

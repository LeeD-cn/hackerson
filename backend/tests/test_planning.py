import copy
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.planning_model import PlanningModel
from backend.store import DomainError
from contracts.planning import AppliedPlan, PlanningDraft
from backend.tests.test_api import ADMIN, call, credential, task


def plan():
    return {'reply': '建议先实现接口，再开发页面。', 'tasks': [
        {'key': 'page', 'name': '报名页面', 'goal': '提交报名', 'dependencies': ['api'],
         'handoff_prompt': '读取 MCP 上下文，按公开接口实现页面，完成后保存进度。'},
        {'key': 'api', 'name': '报名接口', 'goal': '接收报名', 'acceptance': '通过输入校验测试',
         'contract': 'POST /registrations', 'handoff_prompt': '读取上下文，检查代码，实现接口并测试。'},
    ]}


class FakeModel:
    def __init__(self):
        self.value = plan()
        self.calls = []
        self.callback = None

    def generate(self, messages):
        self.calls.append(copy.deepcopy(messages))
        if self.callback:
            self.callback()
        return json.dumps(self.value, ensure_ascii=False)


@pytest.fixture
def planner(tmp_path):
    model = FakeModel()
    db = tmp_path / 'relay.db'
    with TestClient(create_app(db, ADMIN, planning_model=model)) as client:
        yield client, model, db


def request(client, method, path, body=None, status=200, token=ADMIN):
    response = client.request(method, '/api/planning' + path, json=body,
                              headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == status, response.text
    return response.json()


def chat(client, **body):
    return request(client, 'POST', '/chat', {'message': '三个人开发报名系统', **body})


def test_full_workflow_atomic_confirmation_and_restart(planner):
    client, model, db = planner
    draft = PlanningDraft.model_validate(chat(client)).model_dump()
    assert draft['version'] == 1 and draft['status'] == 'draft'
    assert call(client, 'snapshot')['tasks'] == []
    assert len(request(client, 'GET', '/drafts')['drafts']) == 1
    draft = chat(client, draft_id=draft['draft_id'], expected_version=1, message='只保留必要功能')
    assert draft['version'] == 2 and len(draft['messages']) == 4
    edited = draft['plan']
    edited['tasks'][0]['executor'] = '同学 B'
    draft = request(client, 'PUT', f"/drafts/{draft['draft_id']}", {'expected_version': 2, 'plan': edited})
    result = request(client, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 3})
    AppliedPlan.model_validate(result)
    assert result['version'] == 4
    page, api = result['task_ids']['page'], result['task_ids']['api']
    assert next(t for t in result['tasks'] if t['task_id'] == page)['dependencies'] == [api]
    context = call(client, 'get_my_context', credential(client, {'task_id': page}))
    assert context['context']['data']['next_steps'] == edited['tasks'][0]['handoff_prompt']
    assert context['context']['version'] == 2
    assert context['dependency_contracts'][0]['contract'] == 'POST /registrations'
    assert request(client, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 3}) == result
    assert len(call(client, 'snapshot')['tasks']) == 2
    with TestClient(create_app(db, ADMIN, planning_model=FakeModel())) as restarted:
        restored = request(restarted, 'GET', f"/drafts/{draft['draft_id']}")
        assert restored['status'] == 'applied' and restored['plan'] == edited
        assert request(restarted, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 3}) == result
    request(client, 'POST', '/chat', {'message': '再改', 'draft_id': draft['draft_id'], 'expected_version': 4}, 409)


def test_permissions_before_provider_access(planner):
    client, model, _ = planner
    draft = chat(client)
    task_token = credential(client, task(client))
    coordinator = call(client, 'issue_role_token', role='coordinator')['token']
    for token, status in [('', 401), ('invalid', 401), (task_token, 403), (coordinator, 403)]:
        request(client, 'POST', '/chat', {'message': 'secret'}, status, token)
        request(client, 'GET', '/drafts', status=status, token=token)
        request(client, 'GET', f"/drafts/{draft['draft_id']}", status=status, token=token)
        request(client, 'PUT', f"/drafts/{draft['draft_id']}", {'expected_version': 1, 'plan': plan()}, status, token)
        request(client, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 1}, status, token)
    assert len(model.calls) == 1


def test_project_changes_and_context_changes_require_replanning(planner):
    client, model, _ = planner
    existing = task(client)
    token = credential(client, existing)
    draft = chat(client)
    call(client, 'update_my_context', token, expected_version=1, completed='实现一半')
    request(client, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 1}, 409)
    request(client, 'PUT', f"/drafts/{draft['draft_id']}", {'expected_version': 1, 'plan': plan()}, 409)
    model.value['tasks'][0]['dependencies'].append(existing['task_id'])
    draft = chat(client, draft_id=draft['draft_id'], expected_version=1, message='考虑最新进度重新安排')
    assert '实现一半' in model.calls[-1][1]['content']
    result = request(client, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 2})
    assert existing['task_id'] in result['tasks'][0]['dependencies']
    assert len(call(client, 'snapshot')['tasks']) == 3


def test_generation_does_not_lock_database_and_rejects_changed_snapshot(planner):
    client, model, _ = planner
    # A write through a separate request must succeed while the provider is running.
    model.callback = lambda: task(client, 'Concurrent task')
    request(client, 'POST', '/chat', {'message': 'plan'}, 409)
    assert request(client, 'GET', '/drafts')['drafts'] == []
    assert len(call(client, 'snapshot')['tasks']) == 1


def test_stale_draft_versions_cannot_overwrite_or_confirm(planner):
    client, _, _ = planner
    draft = chat(client)
    chat(client, draft_id=draft['draft_id'], expected_version=1)
    for method, path, body in [
        ('POST', '/chat', {'message': 'old', 'draft_id': draft['draft_id'], 'expected_version': 1}),
        ('PUT', f"/drafts/{draft['draft_id']}", {'expected_version': 1, 'plan': plan()}),
        ('POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 1}),
    ]:
        request(client, method, path, body, 409)
    assert call(client, 'snapshot')['tasks'] == []


@pytest.mark.parametrize('kind', ['duplicate', 'missing', 'cycle', 'bad_field', 'bad_key'])
def test_invalid_model_drafts_never_persist(planner, kind):
    client, model, _ = planner
    if kind == 'duplicate':
        model.value['tasks'][0]['key'] = 'api'
    elif kind == 'missing':
        model.value['tasks'][0]['dependencies'] = ['missing']
    elif kind == 'cycle':
        model.value['tasks'][1]['parent_id'] = 'page'
    elif kind == 'bad_field':
        model.value['tasks'][0]['goal'] = ''
    else:
        model.value['tasks'][0]['key'] = 'task_existing'
    request(client, 'POST', '/chat', {'message': 'plan'}, 502)
    assert request(client, 'GET', '/drafts')['drafts'] == []
    assert call(client, 'snapshot')['tasks'] == []


def test_clarification_and_manual_edit_validation(planner):
    client, model, _ = planner
    model.value = {'reply': '请说明截止时间和人数', 'tasks': []}
    draft = chat(client)
    request(client, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 1}, 422)
    invalid = plan()
    invalid['tasks'][0]['dependencies'] = ['missing']
    request(client, 'PUT', f"/drafts/{draft['draft_id']}", {'expected_version': 1, 'plan': invalid}, 422)
    assert request(client, 'GET', f"/drafts/{draft['draft_id']}")['version'] == 1
    request(client, 'POST', '/chat', {'message': 'x', 'draft_id': draft['draft_id']}, 422)
    request(client, 'GET', '/drafts/not-found', status=404)


def test_failure_mid_confirmation_rolls_back_everything(planner):
    client, _, db = planner
    draft = chat(client)
    with sqlite3.connect(db) as connection:
        connection.execute("""CREATE TRIGGER fail_page BEFORE INSERT ON tasks WHEN NEW.name='报名页面'
                              BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
    request(client, 'POST', f"/drafts/{draft['draft_id']}/confirm", {'expected_version': 1}, 500)
    snapshot = call(client, 'snapshot')
    assert snapshot['tasks'] == [] and snapshot['decisions'] == []
    assert request(client, 'GET', f"/drafts/{draft['draft_id']}")['status'] == 'draft'
    with sqlite3.connect(db) as connection:
        assert connection.execute('SELECT count(*) FROM task_contexts').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM context_history').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM notifications').fetchone()[0] == 0


def config():
    return {'RELAY_AI_BASE_URL': 'https://llmapi.paratera.com',
            'RELAY_AI_MODEL': 'DeepSeek-V4-Pro-0813', 'RELAY_AI_API_KEY': 'fake-test-key'}


def test_model_protocol_and_local_key_file(tmp_path):
    key = tmp_path / 'key.txt'
    key.write_text('local-test-secret', encoding='utf-8')
    settings = config()
    del settings['RELAY_AI_API_KEY']
    settings['RELAY_AI_API_KEY_FILE'] = str(key)
    settings['RELAY_AI_JSON_MODE'] = '0'
    calls = []
    def handler(req):
        calls.append(req)
        assert str(req.url) == 'https://llmapi.paratera.com/v1/chat/completions'
        assert req.headers['authorization'] == 'Bearer local-test-secret'
        payload = json.loads(req.content)
        assert payload['model'] == 'DeepSeek-V4-Pro-0813'
        assert 'response_format' not in payload and payload['stream'] is False
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
    model = PlanningModel(settings, httpx.MockTransport(handler))
    assert model.generate([{'role': 'user', 'content': 'JSON'}]) == '{}'
    assert len(calls) == 1


@pytest.mark.parametrize('status,code', [(401, 'ai_auth_failed'), (403, 'ai_auth_failed'),
                                      (429, 'ai_rate_limited'), (500, 'ai_upstream_error'),
                                      (302, 'ai_upstream_error')])
def test_provider_errors_are_sanitized_and_never_retried(status, code):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(status, text='provider-body-containing-secret', headers={'Location': 'https://elsewhere.invalid'})
    with pytest.raises(DomainError) as error:
        PlanningModel(config(), httpx.MockTransport(handler)).generate([])
    assert error.value.code == code and len(calls) == 1
    assert 'secret' not in error.value.message


@pytest.mark.parametrize('failure,code', [('timeout', 'ai_timeout'), ('connection', 'ai_unavailable'),
                                       ('truncated', 'ai_invalid_response'), ('bad_json', 'ai_invalid_response')])
def test_provider_failures(failure, code):
    def handler(req):
        if failure == 'timeout':
            raise httpx.ReadTimeout('private data')
        if failure == 'connection':
            raise httpx.ConnectError('private data')
        if failure == 'truncated':
            return httpx.Response(200, json={'choices': [{'finish_reason': 'length'}]})
        return httpx.Response(200, text='not json')
    with pytest.raises(DomainError) as error:
        PlanningModel(config(), httpx.MockTransport(handler)).generate([])
    assert error.value.code == code


def test_unconfigured_provider_fails_without_draft(tmp_path):
    with TestClient(create_app(tmp_path / 'relay.db', ADMIN, planning_model=PlanningModel({}))) as client:
        result = request(client, 'POST', '/chat', {'message': 'plan'}, 503)
        assert result['error']['code'] == 'ai_not_configured'
        assert request(client, 'GET', '/drafts')['drafts'] == []


@pytest.mark.parametrize('override', [{'RELAY_AI_TIMEOUT_SECONDS': 'nan'},
                                     {'RELAY_AI_BASE_URL': 'https://name:password@example.org'},
                                     {'RELAY_AI_BASE_URL': 'https://example.org:bad'}])
def test_invalid_configuration(override):
    with pytest.raises(DomainError) as error:
        PlanningModel({**config(), **override}).generate([])
    assert error.value.code == 'ai_not_configured'

"""Validate only the shared baseline, using an in-memory database (no app service)."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydantic import ValidationError
from contracts.requests import ContextUpdate, Proposal, StatusUpdate, TaskPatch
from contracts.responses import BootstrapContext, ErrorResponse, QueryModuleResponse


def must_reject(operation, exception):
    try:
        operation()
    except exception:
        return
    raise AssertionError('Invalid input unexpectedly accepted')


def main():
    sample = BootstrapContext.model_validate_json(
        (ROOT / 'contracts/examples/bootstrap.json').read_text(encoding='utf-8'))
    ContextUpdate(expected_version=1, summary='Sample')
    assert ContextUpdate(expected_version=1, summary=None).summary is None
    assert ContextUpdate(expected_version=1, summary='').summary == ''
    assert TaskPatch(parent_id=None).model_dump(exclude_unset=True) == {'parent_id': None}
    query = QueryModuleResponse(contract=sample.dependency_contracts[0], query_id='msg_example',
                                mode='published_contract', notice='Only published information')
    must_reject(lambda: QueryModuleResponse.model_validate({**query.model_dump(), 'mode': 'private_context'}), ValidationError)
    error = ErrorResponse.model_validate({'error': {'code': 'unauthorized', 'message': 'Invalid token'}})
    assert 'details' not in error.model_dump(exclude_none=True)['error']
    ErrorResponse.model_validate({'error': {'code': 'invalid_input', 'message': 'Invalid input',
                                            'details': [{'field': 'expected_version', 'message': 'Field required'}]}})
    must_reject(lambda: ErrorResponse.model_validate({'error': {'code': 'bad', 'message': 'Bad', 'details': ['wrong shape']}}), ValidationError)
    Proposal(task_id='task_api', title='Add field', rationale='Example',
             expected_project_version=3, patch={'contract': 'POST /registrations: {name, student_id}'})
    must_reject(lambda: TaskPatch(), ValidationError)
    must_reject(lambda: TaskPatch(contract=None), ValidationError)
    must_reject(lambda: ContextUpdate(expected_version=1, task_id='someone_else'), ValidationError)
    must_reject(lambda: StatusUpdate(expected_version=1, status='done', progress=50), ValidationError)

    with sqlite3.connect(':memory:') as db:
        schema = (ROOT / 'contracts/schema.sql').read_text(encoding='utf-8')
        db.executescript(schema)
        db.executescript(schema)  # Initial schema is safe to reapply to an unchanged baseline.
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        db.execute('INSERT INTO project(id,name,updated_at) VALUES(1,?,?)', ('Sample', sample.task.created_at))
        for task_id in ['task_api', sample.task.task_id]:
            db.execute('INSERT INTO tasks(task_id,name,goal,created_at,updated_at) VALUES(?,?,?,?,?)',
                       (task_id, task_id, 'Sample goal', sample.task.created_at, sample.task.updated_at))
        db.execute('INSERT INTO task_dependencies VALUES(?,?)', ('task_form', 'task_api'))
        must_reject(lambda: db.execute('INSERT INTO task_dependencies VALUES(?,?)', ('task_form', 'missing')), sqlite3.IntegrityError)
        must_reject(lambda: db.execute('INSERT INTO task_dependencies VALUES(?,?)', ('task_form', 'task_form')), sqlite3.IntegrityError)
        must_reject(lambda: db.execute("UPDATE tasks SET status='invalid' WHERE task_id='task_form'"), sqlite3.IntegrityError)
        must_reject(lambda: db.execute("UPDATE tasks SET status='done',progress=50 WHERE task_id='task_form'"), sqlite3.IntegrityError)
        must_reject(lambda: db.execute('INSERT INTO credentials(token_hash,role,task_id,created_at) VALUES(?,?,?,?)',
                                       ('a' * 64, 'task', None, sample.task.created_at)), sqlite3.IntegrityError)
        db.execute('INSERT INTO task_contexts VALUES(?,?,?,?)',
                   (sample.context.task_id, 1, sample.context.data.model_dump_json(), sample.context.updated_at))
        must_reject(lambda: db.execute("UPDATE task_contexts SET data='invalid JSON'"), sqlite3.IntegrityError)
        decision = sample.decisions[0].model_dump()
        db.execute(f'INSERT INTO decisions({",".join(decision)}) VALUES({",".join("?" for _ in decision)})', tuple(decision.values()))
        notification = sample.notifications[0].model_dump(exclude={'title', 'body'})
        sql = f'INSERT INTO notifications({",".join(notification)}) VALUES({",".join("?" for _ in notification)})'
        db.execute(sql, tuple(notification.values()))
        notification['id'] = 'another_notification'
        must_reject(lambda: db.execute(sql, tuple(notification.values())), sqlite3.IntegrityError)
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        table_count = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    print(json.dumps({'schema_tables': table_count, 'example': 'valid',
                      'constraint_checks': 'passed', 'runtime_features': 'not checked'}, ensure_ascii=False))


if __name__ == '__main__':
    main()

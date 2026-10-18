"""SQLite-backed operations. Every request authenticates inside its transaction."""
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from contracts import requests as req
from contracts import responses as res


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = {
    'snapshot': req.Empty, 'edit_project': req.ProjectEdit,
    'create_task': req.TaskFields, 'edit_task': req.EditTask, 'delete_task': req.DeleteTask,
    'issue_task_token': req.TaskId, 'issue_role_token': req.Credential,
    'list_tasks': req.Empty, 'get_task_status': req.TaskId,
    'get_my_context': req.Empty, 'update_my_context': req.ContextUpdate,
    'report_status': req.StatusUpdate, 'query_module': req.QueryModule,
    'get_project_context': req.Empty, 'get_task_context': req.TaskId,
    'send_message': req.Message, 'get_messages': req.Empty,
    'propose_change': req.Proposal, 'list_changes': req.Empty, 'review_change': req.Approval,
    'get_notifications': req.Empty, 'acknowledge_change': req.NotificationUpdate,
}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return f'{prefix}_{uuid4().hex}'


def dump(value):
    return json.dumps(value, ensure_ascii=False)


class DomainError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = details


def fail(status, code, message):
    raise DomainError(status, code, message)


def require(actor, *roles):
    if actor['role'] not in roles:
        fail(403, 'forbidden', '当前身份没有执行此操作的权限')


def own_task(actor):
    require(actor, 'task')
    return actor['id']


def check_version(actual, expected):
    if actual != expected:
        fail(409, 'version_conflict', f'当前版本为 {actual}，请重新读取后再提交')


class Store:
    def __init__(self, path, admin_token):
        if len(admin_token.encode('utf-8')) < 24:
            raise ValueError('Administrator token must be at least 24 bytes')
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.admin_digest = hashlib.sha256(admin_token.encode('utf-8')).digest()
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f'Unsupported database schema version: {version}')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript((ROOT / 'contracts/schema.sql').read_text(encoding='utf-8'))
            db.execute('INSERT OR IGNORE INTO project(id,name,updated_at) VALUES(1,?,?)',
                       ('我的协作项目', timestamp()))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def run(self, action, arguments, token):
        with self.connect() as db:
            # Serialize read-modify-write operations, including authorization/rotation.
            db.execute('BEGIN IMMEDIATE')
            actor = self.authenticate(db, token)
            if action not in OPERATIONS:
                fail(404, 'unknown_tool', '操作不存在或尚未实现')
            try:
                args = OPERATIONS[action].model_validate(arguments)
            except ValidationError as exc:
                raise DomainError(422, 'invalid_input', '输入参数不合法', [
                    {'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()
                ]) from None
            return getattr(self, action)(db, actor, args)

    def authenticate(self, db, token):
        digest = hashlib.sha256(token.encode('utf-8')).digest()
        if token and hmac.compare_digest(digest, self.admin_digest):
            return {'role': 'admin', 'id': 'admin'}
        row = db.execute('SELECT role,task_id FROM credentials WHERE token_hash=? AND revoked=0',
                         (digest.hex(),)).fetchone()
        if row:
            if row['role'] != 'task' or db.execute(
                    'SELECT 1 FROM tasks WHERE task_id=? AND archived=0', (row['task_id'],)).fetchone():
                return {'role': row['role'], 'id': row['task_id'] or row['role']}
        fail(401, 'unauthorized', '令牌缺失、无效或已撤销')

    def task(self, db, task_id):
        row = db.execute('SELECT * FROM tasks WHERE task_id=? AND archived=0', (task_id,)).fetchone()
        if row is None:
            fail(404, 'task_not_found', '任务不存在或已归档')
        return {**dict(row), 'dependencies': [r[0] for r in db.execute(
            'SELECT depends_on FROM task_dependencies WHERE task_id=? ORDER BY depends_on', (task_id,))]}

    def project(self, db):
        return dict(db.execute('SELECT * FROM project WHERE id=1').fetchone())

    def context(self, db, task_id):
        row = db.execute('SELECT * FROM task_contexts WHERE task_id=?', (task_id,)).fetchone()
        return {**dict(row), 'data': json.loads(row['data'])}

    def task_ids(self, db):
        return [r[0] for r in db.execute('SELECT task_id FROM tasks WHERE archived=0 ORDER BY created_at,task_id')]

    @staticmethod
    def summary(task):
        return {key: task[key] for key in res.TaskSummary.model_fields}

    def public_contract(self, db, task_id):
        task = self.task(db, task_id)
        return {key: task[key] for key in res.PublicContract.model_fields}

    def list_tasks(self, db, actor, args):
        return {'tasks': [self.summary(self.task(db, task_id)) for task_id in self.task_ids(db)],
                'project_version': self.project(db)['version']}

    def get_task_status(self, db, actor, args):
        return self.summary(self.task(db, args.task_id))

    def get_project_context(self, db, actor, args):
        require(actor, 'admin', 'coordinator', 'reviewer')
        return self.project(db)

    def get_task_context(self, db, actor, args):
        require(actor, 'admin', 'coordinator', 'reviewer')
        return {'task': self.task(db, args.task_id), 'context': self.context(db, args.task_id)}

    def get_my_context(self, db, actor, args):
        task_id = own_task(actor)
        task, project = self.task(db, task_id), self.project(db)
        decisions = [dict(r) for r in db.execute('''
            SELECT d.* FROM decisions d JOIN notifications n ON d.id=n.decision_id
            WHERE n.task_id=? ORDER BY d.project_version DESC''', (task_id,))]
        return res.BootstrapContext(
            project_version=project['version'], guidance=project['guidance'],
            task=task, context=self.context(db, task_id),
            dependency_contracts=[self.public_contract(db, dep) for dep in task['dependencies']],
            decisions=decisions, notifications=self.get_notifications(db, actor, req.Empty())['notifications'],
            messages=self.get_messages(db, actor, req.Empty())['messages'], submissions=[],
            instructions='先处理未完成的变更通知，再按 next_steps 继续；工作摘要不能代替真实代码与测试。',
        ).model_dump()

    def validate_graph(self, db, task_id, fields):
        dependencies = fields['dependencies']
        if len(dependencies) != len(set(dependencies)):
            fail(422, 'invalid_input', '依赖不能重复')
        for dep in dependencies:
            if dep == task_id:
                fail(422, 'dependency_cycle', '任务不能依赖自己')
            self.task(db, dep)
        graph = {key: [] for key in self.task_ids(db)}
        for row in db.execute('SELECT * FROM task_dependencies'):
            graph[row['task_id']].append(row['depends_on'])
        graph[task_id] = dependencies
        # Iterative topological traversal avoids recursion limits on long task chains.
        indegree = {key: len(value) for key, value in graph.items()}
        dependents = {key: [] for key in graph}
        for key, deps in graph.items():
            for dep in deps:
                dependents[dep].append(key)
        ready = [key for key, count in indegree.items() if count == 0]
        count = 0
        while ready:
            key = ready.pop()
            count += 1
            for dependent in dependents[key]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if count != len(graph):
            fail(422, 'dependency_cycle', '任务依赖形成循环')
        parent, seen = fields.get('parent_id'), {task_id}
        while parent is not None:
            if parent in seen:
                fail(422, 'parent_cycle', '子任务层级形成循环')
            seen.add(parent)
            parent = self.task(db, parent)['parent_id']

    def affected(self, db, task_id):
        targets = {task_id}
        edges = [(r[0], r[1]) for r in db.execute('SELECT task_id,depends_on FROM task_dependencies')]
        edges += [(r[0], r[1]) for r in db.execute('SELECT task_id,parent_id FROM tasks WHERE archived=0')]
        while True:
            expanded = targets | {child for child, parent in edges if parent in targets}
            if expanded == targets:
                return targets & set(self.task_ids(db))
            targets = expanded

    def record_decision(self, db, actor, task_id, title, body, targets, change_id=None):
        # Callers pass ONLY a curated public summary, never arbitrary edit reasons/private data.
        stamp, decision_id = timestamp(), identifier('dec')
        db.execute('UPDATE project SET version=version+1,updated_at=? WHERE id=1', (stamp,))
        version = self.project(db)['version']
        db.execute('''INSERT INTO decisions(id,project_version,task_id,title,body,actor,change_id,created_at)
                      VALUES(?,?,?,?,?,?,?,?)''',
                   (decision_id, version, task_id, title, body, actor['id'], change_id, stamp))
        targets = sorted(set(targets) & set(self.task_ids(db)))
        db.executemany('''INSERT INTO notifications(id,decision_id,task_id,project_version,created_at)
                          VALUES(?,?,?,?,?)''', [(identifier('ntf'), decision_id, key, version, stamp) for key in targets])
        return {'decision_id': decision_id, 'project_version': version, 'affected_tasks': targets}

    def set_dependencies(self, db, task_id, dependencies):
        db.execute('DELETE FROM task_dependencies WHERE task_id=?', (task_id,))
        db.executemany('INSERT INTO task_dependencies VALUES(?,?)', [(task_id, dep) for dep in dependencies])

    def create_task(self, db, actor, args):
        require(actor, 'admin')
        task_id, stamp = identifier('task'), timestamp()
        fields = args.model_dump()
        self.validate_graph(db, task_id, fields)
        values = {key: value for key, value in fields.items() if key != 'dependencies'}
        values.update(task_id=task_id, created_at=stamp, updated_at=stamp)
        db.execute(f'INSERT INTO tasks({",".join(values)}) VALUES({",".join("?" for _ in values)})', tuple(values.values()))
        self.set_dependencies(db, task_id, fields['dependencies'])
        data = dump({key: '' for key in res.ContextData.model_fields})
        db.execute('INSERT INTO task_contexts VALUES(?,1,?,?)', (task_id, data, stamp))
        db.execute('INSERT INTO context_history VALUES(?,1,?,?)', (task_id, data, stamp))
        event = self.record_decision(db, actor, task_id, f'创建任务：{args.name}', '请读取本任务的启动上下文。', {task_id})
        return {'task': self.task(db, task_id), **event}

    def apply_patch(self, db, actor, task_id, patch, change_id=None):
        task = self.task(db, task_id)
        fields = {**task, **patch}
        self.validate_graph(db, task_id, fields)
        targets = self.affected(db, task_id)
        values = {key: value for key, value in patch.items() if key != 'dependencies'}
        values['updated_at'] = timestamp()
        db.execute(f'UPDATE tasks SET {",".join(key+"=?" for key in values)},version=version+1 WHERE task_id=?',
                   (*values.values(), task_id))
        if 'dependencies' in patch:
            self.set_dependencies(db, task_id, patch['dependencies'])
        targets |= self.affected(db, task_id)
        body = {'changed_fields': sorted(patch), 'instruction': '请重新读取自己的上下文与相关公开接口。'}
        if 'contract' in patch:
            body['contract'] = patch['contract']
        event = self.record_decision(db, actor, task_id, f'更新任务：{fields["name"]}', dump(body), targets, change_id)
        return {'task': self.task(db, task_id), **event}

    def edit_task(self, db, actor, args):
        require(actor, 'admin')
        check_version(self.task(db, args.task_id)['version'], args.expected_version)
        result = self.apply_patch(db, actor, args.task_id, args.patch.model_dump(exclude_unset=True))
        self.add_message(db, actor['id'], 'admin', 'status', dump({'action': 'edit_task', **args.model_dump(exclude_unset=True)}))
        return result

    def delete_task(self, db, actor, args):
        require(actor, 'admin')
        task = self.task(db, args.task_id)
        check_version(task['version'], args.expected_version)
        targets = self.affected(db, args.task_id) - {args.task_id}
        direct = {r[0] for r in db.execute('SELECT task_id FROM task_dependencies WHERE depends_on=?', (args.task_id,))}
        direct |= {r[0] for r in db.execute('SELECT task_id FROM tasks WHERE parent_id=? AND archived=0', (args.task_id,))}
        for key in direct:
            db.execute('UPDATE tasks SET version=version+1,updated_at=? WHERE task_id=?', (timestamp(), key))
        db.execute('UPDATE tasks SET parent_id=NULL WHERE parent_id=?', (args.task_id,))
        db.execute('DELETE FROM task_dependencies WHERE task_id=? OR depends_on=?', (args.task_id, args.task_id))
        db.execute('UPDATE tasks SET archived=1,version=version+1,updated_at=? WHERE task_id=?', (timestamp(), args.task_id))
        db.execute('UPDATE credentials SET revoked=1 WHERE task_id=?', (args.task_id,))
        db.execute("""UPDATE change_requests SET status='rejected',review_note='目标任务已归档',reviewed_by=?,reviewed_at=?
                      WHERE task_id=? AND status='pending'""", (actor['id'], timestamp(), args.task_id))
        self.add_message(db, actor['id'], 'admin', 'status', dump({'action': 'delete_task', **args.model_dump()}))
        return self.record_decision(db, actor, args.task_id, f'归档任务：{task["name"]}',
                                    '相关依赖或父任务关系已移除，请重新读取启动上下文。', targets)

    def edit_project(self, db, actor, args):
        require(actor, 'admin')
        check_version(self.project(db)['version'], args.expected_version)
        db.execute('UPDATE project SET name=?,goal=?,private_context=?,guidance=? WHERE id=1',
                   (args.name, args.goal, args.private_context, args.guidance))
        self.add_message(db, actor['id'], 'admin', 'status', dump({'action': 'edit_project', 'reason': args.reason}))
        return self.record_decision(db, actor, None, '项目规范已更新',
                                    '请读取启动上下文中的最新授权规范摘要。', self.task_ids(db))

    def issue_token(self, db, role, task_id=None):
        token = secrets.token_urlsafe(32)
        db.execute('INSERT INTO credentials(token_hash,role,task_id,created_at) VALUES(?,?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(), role, task_id, timestamp()))
        return {'token': token, 'role': role, 'task_id': task_id, 'notice': '令牌仅本次显示；同一身份的旧令牌已撤销。'}

    def issue_task_token(self, db, actor, args):
        require(actor, 'admin')
        self.task(db, args.task_id)
        db.execute('UPDATE credentials SET revoked=1 WHERE task_id=?', (args.task_id,))
        return self.issue_token(db, 'task', args.task_id)

    def issue_role_token(self, db, actor, args):
        require(actor, 'admin')
        db.execute('UPDATE credentials SET revoked=1 WHERE role=?', (args.role,))
        return self.issue_token(db, args.role)

    def update_my_context(self, db, actor, args):
        task_id = own_task(actor)
        context = self.context(db, task_id)
        check_version(context['version'], args.expected_version)
        updates = args.model_dump(exclude_none=True, exclude={'expected_version'})
        if not updates:
            fail(422, 'invalid_input', '至少更新一个非 null 的上下文字段')
        data, stamp, version = dump({**context['data'], **updates}), timestamp(), context['version'] + 1
        db.execute('UPDATE task_contexts SET version=?,data=?,updated_at=? WHERE task_id=?', (version, data, stamp, task_id))
        db.execute('INSERT INTO context_history VALUES(?,?,?,?)', (task_id, version, data, stamp))
        return self.context(db, task_id)

    def report_status(self, db, actor, args):
        task_id = own_task(actor)
        check_version(self.task(db, task_id)['version'], args.expected_version)
        if args.status == 'done' and db.execute("SELECT 1 FROM notifications WHERE task_id=? AND status!='completed'", (task_id,)).fetchone():
            fail(409, 'outstanding_changes', '任务还有未完成的变更通知')
        db.execute('UPDATE tasks SET status=?,progress=?,version=version+1,updated_at=? WHERE task_id=?',
                   (args.status, args.progress, timestamp(), task_id))
        if args.note:
            self.add_message(db, actor['id'], 'coordinator', 'status', args.note)
        return self.summary(self.task(db, task_id))

    def add_message(self, db, sender, target, kind, body, reply_to=None):
        message_id = identifier('msg')
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (message_id, sender, target, kind, body, reply_to, timestamp()))
        return dict(db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone())

    def query_module(self, db, actor, args):
        contract = self.public_contract(db, args.task_id)
        query = self.add_message(db, actor['id'], 'coordinator', 'query', dump({'task_id': args.task_id, 'question': args.question}))
        self.add_message(db, 'coordinator', actor['id'], 'contract_response', dump(contract), query['id'])
        return {'contract': contract, 'query_id': query['id'], 'mode': 'published_contract',
                'notice': '仅返回已发布接口；超出契约的问题由协调者通过消息回复。'}

    def send_message(self, db, actor, args):
        if args.target not in {'admin', 'coordinator', 'reviewer'}:
            self.task(db, args.target)
        if args.reply_to:
            row = db.execute('SELECT * FROM messages WHERE id=?', (args.reply_to,)).fetchone()
            if row is None or (actor['role'] == 'task' and actor['id'] not in {row['sender'], row['target']}):
                fail(404, 'message_not_found', '原消息不存在或不可见')
        return self.add_message(db, actor['id'], args.target, 'message', args.body, args.reply_to)

    def get_messages(self, db, actor, args):
        sql, params = 'SELECT * FROM messages', ()
        if actor['role'] == 'task':
            sql += ' WHERE sender=? OR target=?'
            params = (actor['id'], actor['id'])
        return {'messages': [dict(row) for row in db.execute(sql + ' ORDER BY created_at DESC,id', params)]}

    def propose_change(self, db, actor, args):
        require(actor, 'admin', 'coordinator', 'task')
        task = self.task(db, args.task_id)
        check_version(self.project(db)['version'], args.expected_project_version)
        patch = args.patch.model_dump(exclude_unset=True)
        self.validate_graph(db, args.task_id, {**task, **patch})
        change_id = identifier('chg')
        db.execute('''INSERT INTO change_requests(id,proposer,task_id,title,rationale,patch,base_version,created_at)
                      VALUES(?,?,?,?,?,?,?,?)''',
                   (change_id, actor['id'], args.task_id, args.title, args.rationale, dump(patch), args.expected_project_version, timestamp()))
        return {'change_id': change_id, 'status': 'pending', 'affected_tasks': sorted(self.affected(db, args.task_id))}

    def list_changes(self, db, actor, args):
        sql, params = 'SELECT * FROM change_requests', ()
        if actor['role'] == 'task':
            sql += ' WHERE proposer=? OR task_id=?'
            params = (actor['id'], actor['id'])
        return {'changes': [{**dict(row), 'patch': json.loads(row['patch'])} for row in db.execute(sql + ' ORDER BY created_at DESC,id', params)]}

    def review_change(self, db, actor, args):
        require(actor, 'admin')
        change = db.execute('SELECT * FROM change_requests WHERE id=?', (args.change_id,)).fetchone()
        if change is None:
            fail(404, 'change_not_found', '提案不存在')
        if change['status'] != 'pending':
            fail(409, 'already_reviewed', '提案已经处理')
        event = {}
        if args.approve:
            check_version(self.project(db)['version'], change['base_version'])
            applied = self.apply_patch(db, actor, change['task_id'], json.loads(change['patch']), args.change_id)
            event = {key: applied[key] for key in res.ChangeEvent.model_fields}
        status = 'approved' if args.approve else 'rejected'
        db.execute('UPDATE change_requests SET status=?,review_note=?,reviewed_by=?,reviewed_at=? WHERE id=?',
                   (status, args.note, actor['id'], timestamp(), args.change_id))
        return {'change_id': args.change_id, 'status': status, **event}

    def get_notifications(self, db, actor, args):
        sql = '''SELECT n.*,d.title,d.body FROM notifications n JOIN decisions d ON n.decision_id=d.id
                 JOIN tasks t ON n.task_id=t.task_id WHERE t.archived=0'''
        params = ()
        if actor['role'] == 'task':
            sql += ' AND n.task_id=?'
            params = (actor['id'],)
        return {'notifications': [dict(row) for row in db.execute(sql + ' ORDER BY n.project_version DESC,n.id', params)]}

    def acknowledge_change(self, db, actor, args):
        task_id = own_task(actor)
        row = db.execute('SELECT * FROM notifications WHERE id=? AND task_id=?', (args.notification_id, task_id)).fetchone()
        if row is None:
            fail(404, 'notification_not_found', '通知不存在或不可见')
        if row['status'] != args.status:
            if (row['status'], args.status) not in {('pending', 'acknowledged'), ('acknowledged', 'completed')}:
                fail(409, 'invalid_transition', '通知需先确认理解，再报告完成修改；不能倒退状态')
            column = 'acknowledged_at' if args.status == 'acknowledged' else 'completed_at'
            db.execute(f'UPDATE notifications SET status=?,note=?,{column}=? WHERE id=?',
                       (args.status, args.note, timestamp(), args.notification_id))
        return dict(db.execute('''SELECT n.*,d.title,d.body FROM notifications n
                                  JOIN decisions d ON n.decision_id=d.id WHERE n.id=?''', (args.notification_id,)).fetchone())

    def snapshot(self, db, actor, args):
        require(actor, 'admin', 'coordinator', 'reviewer')
        tasks = [self.task(db, key) for key in self.task_ids(db)]
        return res.Snapshot(
            project=self.project(db), tasks=tasks,
            contexts={task['task_id']: self.context(db, task['task_id']) for task in tasks},
            messages=self.get_messages(db, actor, req.Empty())['messages'],
            changes=self.list_changes(db, actor, req.Empty())['changes'],
            notifications=self.get_notifications(db, actor, req.Empty())['notifications'],
            decisions=[dict(row) for row in db.execute('SELECT * FROM decisions ORDER BY project_version DESC')],
            submissions=[], role=actor['role'],
        ).model_dump()

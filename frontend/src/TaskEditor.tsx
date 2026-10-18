import { useRef, useState, type FormEvent } from 'react';
import { ApiError, asError, call } from './api';
import { ErrorNotice, Modal } from './components';
import type { Snapshot, Task, TaskFields, TaskResult } from './types';

const emptyFields = (): TaskFields => ({ name: '', goal: '', description: '', acceptance: '', contract: '', constraints: '', dependencies: [], parent_id: null, executor: '', branch: '' });
function fieldsOf(task: Task): TaskFields {
  const { name, goal, description, acceptance, contract, constraints, dependencies, parent_id, executor, branch } = task;
  return { name, goal, description, acceptance, contract, constraints, dependencies, parent_id, executor, branch };
}

export default function TaskEditor({ task, tasks, token, onClose, onSaved, onSnapshot, onExpired }: {
  task: Task | null; tasks: Task[]; token: string; onClose: () => void;
  onSaved: (result: TaskResult) => Promise<void>; onSnapshot: (snapshot: Snapshot) => void; onExpired: () => void;
}) {
  const [fields, setFields] = useState<TaskFields>(() => task ? fieldsOf(task) : emptyFields());
  const [base, setBase] = useState<Task | null>(task);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [reloaded, setReloaded] = useState(false);
  const [unknownWrite, setUnknownWrite] = useState(false);
  const [showReason, setShowReason] = useState(false);
  const dirty = JSON.stringify(fields) !== JSON.stringify(base ? fieldsOf(base) : emptyFields()) || !!reason;
  const choices = tasks.filter(t => t.task_id !== task?.task_id);
  const update = <K extends keyof TaskFields>(key: K, value: TaskFields[K]) => setFields(f => ({ ...f, [key]: value }));

  const close = () => { if (!busy && (!dirty || window.confirm('有尚未保存的内容，确定放弃草稿吗？'))) onClose(); };
  async function reloadLatest() {
    if (!base || !window.confirm('将用服务器最新内容替换当前草稿，是否继续？')) return;
    setBusy(true);
    try {
      const snapshot = await call<Snapshot>(token, 'snapshot');
      const latest = snapshot.tasks.find(t => t.task_id === base.task_id);
      if (!latest) throw new ApiError(404, 'task_not_found', '该任务已被归档，请关闭编辑窗口并刷新列表。');
      onSnapshot(snapshot); setBase(latest); setFields(fieldsOf(latest)); setError(null); setReloaded(true); setUnknownWrite(false);
    } catch (err) { const problem = asError(err); setError(problem); if (problem.status === 401) onExpired(); }
    finally { setBusy(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current) return;
    if (!fields.name.trim() || !fields.goal.trim() || (base && !reason.trim())) {
      setError(new ApiError(422, 'invalid_input', '任务名称、目标及修改理由不能只包含空格。')); return;
    }
    const patch = Object.fromEntries(Object.entries(fields).filter(([key, value]) => !base || JSON.stringify(value) !== JSON.stringify(fieldsOf(base)[key as keyof TaskFields])));
    if (base && !Object.keys(patch).length) { setError(new ApiError(422, 'empty_patch', '尚未修改任何任务字段。')); return; }
    inFlight.current = true; setBusy(true); setError(null); setReloaded(false);
    try {
      const result = await call<TaskResult>(token, base ? 'edit_task' : 'create_task', base
        ? { task_id: base.task_id, expected_version: base.version, patch, reason: reason.trim() }
        : { ...fields, name: fields.name.trim(), goal: fields.goal.trim() });
      // A successful write is never retried if refreshing the view subsequently fails.
      await onSaved(result);
    } catch (err) {
      const problem = asError(err); setError(problem);
      if (problem.code === 'network_error' || problem.status >= 500) setUnknownWrite(true);
      if (problem.status === 401) onExpired();
    } finally { inFlight.current = false; setBusy(false); }
  }

  return <Modal title={base ? '编辑任务' : '创建新任务'} onClose={close} wide>
    <form onSubmit={submit} className="task-form">
      <div className="form-body">
        <p className="form-intro">{base ? `编辑基于任务 v${base.version}。保存后由后端通知受影响的任务。` : '按功能、模块或具体目标定义任务，稍后可以继续拆分与关联。'}</p>
        <ErrorNotice error={error}>
          {error?.code === 'version_conflict' && <button type="button" className="button small" disabled={busy} onClick={reloadLatest}>载入最新版本并替换草稿</button>}
          {unknownWrite && <p>为避免重复写入，请先关闭此窗口并刷新列表，确认结果后再提交。</p>}
        </ErrorNotice>
        {reloaded && <p role="status" className="success-note">已载入最新版本，请重新核对并编辑。</p>}
        <fieldset disabled={busy}>
          <label>任务名称 <span className="required">*</span><input autoFocus required maxLength={160} value={fields.name} onChange={e => update('name', e.target.value)} placeholder="例如：实现活动报名接口"/></label>
          <label>任务目标 <span className="required">*</span><textarea required maxLength={10000} rows={3} value={fields.goal} onChange={e => update('goal', e.target.value)} placeholder="这个任务需要达成什么结果？"/></label>
          <div className="form-grid">
            <label>执行者<input maxLength={200} value={fields.executor} onChange={e => update('executor', e.target.value)} placeholder="成员或执行者名称（可选）"/></label>
            <label>Git 分支<input maxLength={500} value={fields.branch} onChange={e => update('branch', e.target.value)} placeholder="feature/your-task"/></label>
          </div>
          <label>验收标准<textarea rows={3} maxLength={20000} value={fields.acceptance} onChange={e => update('acceptance', e.target.value)} placeholder="如何判断这项任务已经完成？"/></label>
          <div className="form-grid relationships">
            <label>父任务<select value={fields.parent_id || ''} onChange={e => update('parent_id', e.target.value || null)}><option value="">无父任务（顶层任务）</option>{choices.map(t => <option key={t.task_id} value={t.task_id}>{t.name}</option>)}</select><small>用于组织层级，不等同于开发依赖。</small></label>
            <div><span className="field-label">依赖任务</span><div className="dependency-options">{!choices.length && <p className="muted">创建其他任务后即可关联。</p>}{choices.map(t => <label className="checkbox-row" key={t.task_id}><input type="checkbox" checked={fields.dependencies.includes(t.task_id)} onChange={e => update('dependencies', e.target.checked ? [...fields.dependencies, t.task_id] : fields.dependencies.filter(id => id !== t.task_id))}/><span>{t.name}</span></label>)}</div><small>需先完成或对齐的任务；后端会检查循环依赖。</small></div>
          </div>
          <details className="advanced-fields"><summary>详细描述、接口契约与技术约束</summary>
            <label>详细描述<textarea rows={3} maxLength={20000} value={fields.description} onChange={e => update('description', e.target.value)}/></label>
            <label>公开接口契约<textarea rows={4} maxLength={30000} value={fields.contract} onChange={e => update('contract', e.target.value)} placeholder="其他任务可以查询到的接口信息"/></label>
            <label>技术约束<textarea rows={3} maxLength={20000} value={fields.constraints} onChange={e => update('constraints', e.target.value)}/></label>
          </details>
          {base && <label>修改理由 <span className="required">*</span><textarea required rows={2} maxLength={5000} value={reason} onFocus={() => setShowReason(true)} onChange={e => setReason(e.target.value)} placeholder="说明本次调整的原因"/>{showReason && <small>修改理由会保存在后台管理记录中。</small>}</label>}
        </fieldset>
      </div>
      <footer className="modal-footer"><span className="muted">{base ? '任务状态由对应执行者报告' : '新任务默认处于「待开始」'}</span><div><button type="button" className="button" onClick={close} disabled={busy}>取消</button><button className="button primary" disabled={busy || unknownWrite}>{busy ? '正在保存…' : base ? '保存修改' : '创建任务'}</button></div></footer>
    </form>
  </Modal>;
}

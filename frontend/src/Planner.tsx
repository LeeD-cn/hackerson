import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, asError, planningRequest } from './api';
import { ErrorNotice, Icon, Modal, formatTime } from './components';
import type { AppliedPlan, DraftSummary, PlanContent, PlannedTask, PlanningDraft } from './planningTypes';
import type { Task } from './types';
import './planner.css';

type EditableTask = PlannedTask & { dependencyText: string; parentText: string };
const examples = ['我们三个人，用两小时开发活动报名系统。请拆分最小任务，安排依赖，并生成各自的开发提示词。',
  '请根据已有任务和当前进度，规划接下来最重要的工作，不要重复安排已完成的部分。'];

function assistantReply(content: string) {
  try { const value = JSON.parse(content); return typeof value.reply === 'string' ? value.reply : content; }
  catch { return content; }
}

export default function Planner({ token, tasks, onApplied, onShowTasks, onExpired }: {
  token: string; tasks: Task[]; onApplied: (result: AppliedPlan) => Promise<void>;
  onShowTasks: () => void; onExpired: () => void;
}) {
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [draft, setDraft] = useState<PlanningDraft | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<ApiError | null>(null);
  const [dirty, setDirty] = useState(false);
  const [editedTasks, setEditedTasks] = useState<EditableTask[]>([]);
  const [reply, setReply] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [created, setCreated] = useState<number | null>(null);
  const alive = useRef(true);
  const conversation = useRef<HTMLDivElement>(null);

  function accept(next: PlanningDraft | null) {
    setDraft(next); setDirty(false); setCreated(null); setReply(next?.plan.reply || '');
    setEditedTasks(next?.plan.tasks.map(t => ({ ...t, dependencyText: t.dependencies.join(', '), parentText: t.parent_id || '' })) || []);
  }
  function problem(value: unknown) {
    const error = asError(value); setError(error);
    if (error.status === 401) onExpired();
  }
  async function summaries() {
    const result = await planningRequest<{ drafts: DraftSummary[] }>(token, '/drafts');
    if (alive.current) setDrafts(result.drafts);
  }
  useEffect(() => {
    alive.current = true;
    setBusy('load');
    planningRequest<{ drafts: DraftSummary[] }>(token, '/drafts').then(result => {
      if (alive.current) setDrafts(result.drafts);
    }).catch(err => { if (alive.current) problem(err); }).finally(() => { if (alive.current) setBusy(''); });
    return () => { alive.current = false; };
  }, [token]);
  useEffect(() => { conversation.current?.scrollTo({ top: conversation.current.scrollHeight, behavior: 'smooth' }); }, [draft?.messages.length, busy]);

  async function load(id: string) {
    setBusy('load'); setError(null);
    try { const result = await planningRequest<PlanningDraft>(token, `/drafts/${encodeURIComponent(id)}`); if (alive.current) accept(result); }
    catch (err) { if (alive.current) problem(err); }
    finally { if (alive.current) setBusy(''); }
  }
  async function send(event: FormEvent) {
    event.preventDefault();
    if (!message.trim() || busy || dirty || draft?.status === 'applied') return;
    setBusy('chat'); setError(null);
    try {
      const next = await planningRequest<PlanningDraft>(token, '/chat', 'POST', {
        message: message.trim(), ...(draft ? { draft_id: draft.draft_id, expected_version: draft.version } : {}),
      });
      if (!alive.current) return;
      accept(next); setMessage(''); await summaries();
    } catch (err) { if (alive.current) problem(err); }
    finally { if (alive.current) setBusy(''); }
  }
  async function save() {
    if (!draft || busy) return;
    const plan: PlanContent = { reply, tasks: editedTasks.map(({ dependencyText, parentText, ...task }) => ({
      ...task, dependencies: dependencyText.split(/[,，\n]/).map(s => s.trim()).filter(Boolean), parent_id: parentText.trim() || null,
    })) };
    setBusy('edit'); setError(null);
    try {
      const next = await planningRequest<PlanningDraft>(token, `/drafts/${draft.draft_id}`, 'PUT', { expected_version: draft.version, plan });
      if (alive.current) { accept(next); await summaries(); }
    } catch (err) { if (alive.current) problem(err); }
    finally { if (alive.current) setBusy(''); }
  }
  async function confirm() {
    if (!draft || busy || dirty) return;
    setBusy('confirm'); setError(null);
    try {
      const result = await planningRequest<AppliedPlan>(token, `/drafts/${draft.draft_id}/confirm`, 'POST', { expected_version: draft.version });
      if (!alive.current) return;
      accept({ ...draft, status: 'applied', version: result.version });
      setCreated(result.tasks.length); setConfirming(false);
      await onApplied(result); if (alive.current) await summaries();
    } catch (err) { if (alive.current) { setConfirming(false); problem(err); } }
    finally { if (alive.current) setBusy(''); }
  }
  function edit(index: number, field: keyof EditableTask, value: string) {
    setEditedTasks(current => current.map((t, i) => i === index ? { ...t, [field]: value } : t)); setDirty(true);
  }
  const applied = draft?.status === 'applied';
  const disabled = !!busy || applied;
  const taskName = (ref: string) => editedTasks.find(t => t.key === ref)?.name || tasks.find(t => t.task_id === ref)?.name || ref;

  return <section className="planner" aria-label="AI 任务规划">
    <div className="planner-toolbar"><label>规划记录<select aria-label="选择规划记录" value={draft?.draft_id || ''} disabled={!!busy || dirty} onChange={e => e.target.value ? void load(e.target.value) : accept(null)}>
      <option value="">新规划</option>{drafts.map(item => <option key={item.draft_id} value={item.draft_id}>{formatTime(item.updated_at)} · {item.reply.slice(0, 28)} · {item.status === 'applied' ? '已创建' : `${item.task_count} 项草案`}</option>)}</select></label>
      <button className="button" disabled={!!busy || dirty} onClick={() => { accept(null); setMessage(''); setError(null); }}><Icon name="plus" size={16}/>新规划</button>
      <span className="muted">基于当前 {tasks.length} 项任务 · 仅在确认后创建</span>
    </div>
    <ErrorNotice error={error}>{draft && error?.status === 409 && <p>草案冲突请重新载入；项目进度发生变化时，请继续对话，让 AI 根据最新信息调整。</p>}
      {draft && <button className="button small" disabled={!!busy} onClick={() => void load(draft.draft_id)}>重新载入已保存草案</button>}
    </ErrorNotice>
    {created !== null && <div className="success-banner" role="status"><Icon name="check" size={18}/><span>已创建 {created} 项任务，交接提示词已保存。</span><button className="button small" onClick={onShowTasks}>查看任务</button></div>}
    <div className="planner-layout">
      <section className="planner-chat" aria-label="规划对话">
        <header className="planner-panel-heading"><span className="planner-avatar"><Icon name="chat"/></span><div><h2>项目规划助手</h2><p>说清目标，一起把工作分好。</p></div><span className="planner-ai-label">AI</span></header>
        <div className="planner-messages" ref={conversation} aria-live="polite" aria-busy={busy === 'chat'}>
          {!draft && <div className="planner-welcome"><span className="eyebrow">LET’S MAKE A PLAN</span><h3>这次想和团队做些什么？</h3><p>告诉我项目目标、团队人数、剩余时间和技术要求。我会结合已有任务，给出可修改的分工与交接提示词。</p><div className="planner-examples">{examples.map((text, i) => <button key={text} disabled={!!busy} onClick={() => setMessage(text)}><Icon name={i ? 'branch' : 'grid'} size={18}/><span>{i ? '基于已有进度继续规划' : '从一个活动报名系统开始'}</span><Icon name="arrow" size={15}/></button>)}</div></div>}
          {draft?.messages.map((item, index) => <article key={index} className={`planner-message ${item.role}`}><small>{item.role === 'user' ? '你' : '规划助手'}</small><p>{item.role === 'assistant' ? assistantReply(item.content) : item.content}</p></article>)}
          {busy === 'chat' && <div className="planner-thinking" role="status"><span/>正在结合项目情况规划，请稍候…</div>}
        </div>
        <form className="planner-composer" onSubmit={send}><label htmlFor="planning-message">{applied ? '此规划已创建任务，点击“新规划”开始下一次讨论。' : '描述需求，或继续调整当前草案'}</label>
          <textarea id="planning-message" aria-label="规划需求" rows={4} maxLength={12000} value={message} disabled={!!busy || applied || dirty} onChange={e => setMessage(e.target.value)} placeholder="例如：三个人，两小时，先做报名和名额限制，暂不做支付…"/>
          <div><small>{dirty ? '请先保存或撤销右侧修改，再继续对话。' : 'AI 生成规划建议；你确认后才会写入任务。'}</small><button className="button primary" disabled={!!busy || !message.trim() || applied || dirty}>{busy === 'chat' ? '规划中…' : '发送'}<Icon name="arrow" size={16}/></button></div>
        </form>
      </section>
      <section className="planner-preview" aria-label="任务草案">
        <header className="planner-panel-heading"><div><span className="eyebrow">TASK PLAN</span><h2>{applied ? '已创建的任务规划' : '任务草案'} <span className="planner-count">{editedTasks.length}</span></h2></div>{draft && <span className="version">v{draft.version}</span>}</header>
        {!draft ? <div className="planner-empty"><Icon name="branch" size={34}/><h3>先聊目标，再看分工</h3><p>生成后在这里检查任务目标、依赖、验收标准和开发提示词。</p></div> : <>
          <div className="planner-preview-body"><p className="planner-draft-note">{applied ? '任务已保存。开发者可读取任务上下文继续工作。' : editedTasks.length ? '可以直接修改下方内容，保存草案后再确认创建。' : '还需要补充信息，请继续对话。'}</p>
            {editedTasks.map((task, index) => <article className="planned-task" key={`${draft.draft_id}-${index}`}>
              <div className="planned-task-top"><span>{String(index + 1).padStart(2, '0')}</span><code>{task.key}</code>{!applied && <button className="icon-button" aria-label={`移除任务 ${task.name}`} disabled={!!busy} onClick={() => { setEditedTasks(items => items.filter((_, i) => i !== index)); setDirty(true); }}><Icon name="close" size={15}/></button>}</div>
              <label>任务名称<input aria-label={`任务 ${index + 1} 名称`} value={task.name} maxLength={160} disabled={disabled} onChange={e => edit(index, 'name', e.target.value)}/></label>
              <label>任务目标<textarea rows={2} value={task.goal} maxLength={10000} disabled={disabled} onChange={e => edit(index, 'goal', e.target.value)}/></label>
              <div className="planner-field-row"><label>执行者<input value={task.executor} maxLength={200} disabled={disabled} onChange={e => edit(index, 'executor', e.target.value)} placeholder="待分配"/></label><label>依赖标识<input value={task.dependencyText} disabled={disabled} onChange={e => edit(index, 'dependencyText', e.target.value)} placeholder="逗号分隔 key 或 task_id"/></label></div>
              {task.dependencyText && <p className="planned-dependencies">依赖：{task.dependencyText.split(/[,，\n]/).filter(s => s.trim()).map(ref => taskName(ref.trim())).join('、')}</p>}
              <label>验收标准<textarea rows={2} value={task.acceptance} maxLength={20000} disabled={disabled} onChange={e => edit(index, 'acceptance', e.target.value)}/></label>
              <details><summary>接口约定与其他说明</summary>{([['contract', '公开接口契约', 30000], ['description', '详细描述', 20000], ['constraints', '技术约束', 20000]] as const).map(([key, title, max]) => <label key={key}>{title}<textarea rows={2} value={task[key]} maxLength={max} disabled={disabled} onChange={e => edit(index, key, e.target.value)}/></label>)}<label>Git 分支<input value={task.branch} maxLength={500} disabled={disabled} onChange={e => edit(index, 'branch', e.target.value)}/></label><label>父任务标识<input value={task.parentText} disabled={disabled} onChange={e => edit(index, 'parentText', e.target.value)} placeholder="可选 key 或 task_id"/></label></details>
              <details><summary>给开发 AI 的交接提示词</summary><label>交接提示词<textarea rows={6} value={task.handoff_prompt} maxLength={16000} disabled={disabled} onChange={e => edit(index, 'handoff_prompt', e.target.value)}/></label></details>
            </article>)}
            {dirty && <p className="planner-unsaved" role="status">有未保存的修改。移除任务后，请同步调整其他任务的依赖。</p>}
          </div>
          <footer className="planner-confirm-bar">{dirty ? <><button className="button" disabled={!!busy} onClick={() => accept(draft)}>撤销修改</button><button className="button primary" disabled={!!busy} onClick={() => void save()}>{busy === 'edit' ? '保存中…' : '保存草案'}</button></> : applied ? <button className="button" onClick={onShowTasks}>查看任务空间<Icon name="arrow" size={16}/></button> : <><span>确认后创建 {editedTasks.length} 项任务</span><button className="button primary" disabled={!!busy || !editedTasks.length} onClick={() => setConfirming(true)}><Icon name="check" size={16}/>确认创建任务</button></>}</footer>
        </>}
      </section>
    </div>
    {confirming && <Modal title="确认创建任务" onClose={() => { if (!busy) setConfirming(false); }}><div className="planner-confirm-dialog"><p>将把这份草案中的 {editedTasks.length} 项任务加入当前项目，并保存各自的开发交接提示词。</p><ul>{editedTasks.map(task => <li key={task.key}>{task.name}</li>)}</ul><p className="muted">这一步不会启动开发 AI。任务创建后，可以在任务空间查看并继续安排执行者。</p><ErrorNotice error={error}/><div className="planner-dialog-actions"><button className="button" disabled={!!busy} onClick={() => setConfirming(false)}>继续检查</button><button className="button primary" disabled={!!busy} onClick={() => void confirm()}>{busy === 'confirm' ? '正在创建…' : '创建这些任务'}</button></div></div></Modal>}
  </section>;
}

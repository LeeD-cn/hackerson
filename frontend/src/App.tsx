import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ApiError, asError, call, checkHealth } from './api';
import { ErrorNotice, Icon, TextBlock, formatTime } from './components';
import TaskEditor from './TaskEditor';
import { notificationLabels, statusLabels, type Notification, type Snapshot, type Task, type TaskResult, type TaskStatus } from './types';

const SESSION_KEY = 'relay.console.token';
function storedToken() { try { return sessionStorage.getItem(SESSION_KEY) || ''; } catch { return ''; } }
function rememberToken(token: string) { try { if (token) sessionStorage.setItem(SESSION_KEY, token); else sessionStorage.removeItem(SESSION_KEY); } catch { /* In-memory authentication still works when storage is disabled. */ } }

function Login({ busy, error, onConnect }: { busy: boolean; error: ApiError | null; onConnect: (token: string, remember: boolean) => void }) {
  const [value, setValue] = useState('');
  const [remember, setRemember] = useState(true);
  const submit = (event: FormEvent) => { event.preventDefault(); if (value.trim()) onConnect(value.trim(), remember); };
  return <div className="login-page">
    <div className="login-story"><a className="brand" href="/"><span className="brand-mark">r</span>relay<span className="brand-caption">协作控制台</span></a>
      <div className="story-content"><span className="eyebrow">SHARED CONTEXT. CONNECTED WORK.</span><h1>让每一项工作，<br/>接得上。</h1><p>任务、上下文与接口约定集中在一处。<br/>换一个会话，继续同一项工作。</p>
        <div className="story-diagram" aria-hidden="true"><div className="story-node"><span className="mini-icon"><Icon name="grid"/></span><div><strong>稳定的任务身份</strong><small>目标 · 验收 · 工作记录</small></div><span className="dot"/></div><div className="connector-line"/><div className="story-node offset"><span className="mini-icon purple"><Icon name="branch"/></span><div><strong>共享的接口约定</strong><small>依赖 · 变更 · 确认状态</small></div><span className="dot purple-dot"/></div></div>
      </div><p className="story-foot">一个后台，连接团队的独立开发会话。</p>
    </div>
    <div className="login-side"><form className="login-card" onSubmit={submit}><span className="eyebrow">CONNECT YOUR WORKSPACE</span><h2>连接项目空间</h2><p className="muted">使用当前后台的管理员令牌登录。</p>
      <ErrorNotice error={error}/><label>访问令牌<input type="password" autoComplete="off" autoFocus required value={value} onChange={e => setValue(e.target.value)} placeholder="粘贴管理员令牌" disabled={busy}/></label>
      <label className="checkbox-row remember"><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)}/><span>在当前标签页记住令牌</span></label>
      <button className="button primary login-button" disabled={busy}>{busy ? '正在连接…' : '进入工作空间'}<Icon name="arrow" size={18}/></button>
      <div className="connection-help"><strong>首次连接</strong><p>先按 backend/README.md 启动后台，再从后台所在目录的 <code>.local/admin-token.txt</code> 获取令牌。</p><p>令牌只用于访问当前后台，不会写入代码。协调者和审核者可以只读查看。</p></div>
    </form></div>
  </div>;
}

function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`badge status-${status}`}><span/>{statusLabels[status]}</span>;
}

function NotificationCard({ item, taskName, onSelect }: { item: Notification; taskName?: string; onSelect?: () => void }) {
  return <article className="notification-card"><div className="notification-heading"><span className={`badge notification-${item.status}`}>{notificationLabels[item.status]}</span><span className="muted">项目 v{item.project_version}</span></div><h3>{item.title}</h3>
    {taskName && <button type="button" className="text-button" onClick={onSelect}>{taskName}<Icon name="arrow" size={14}/></button>}
    <p className="notification-body">{item.body}</p>{item.note && <p className="notification-note">执行者说明：{item.note}</p>}<time>{formatTime(item.created_at)}</time>
  </article>;
}

function TaskDetail({ task, snapshot, onSelect, onEdit }: { task: Task; snapshot: Snapshot; onSelect: (id: string) => void; onEdit: () => void }) {
  const [tab, setTab] = useState<'brief' | 'context' | 'changes'>('brief');
  const context = snapshot.contexts[task.task_id];
  const notices = snapshot.notifications.filter(n => n.task_id === task.task_id);
  const dependents = snapshot.tasks.filter(t => t.dependencies.includes(task.task_id));
  const taskLink = (id: string) => <button key={id} type="button" className="task-link" onClick={() => onSelect(id)}>{snapshot.tasks.find(t => t.task_id === id)?.name || id}<Icon name="arrow" size={14}/></button>;
  return <aside className="detail-panel" aria-label="任务详情">
    <div className="detail-heading"><div className="detail-label"><span className="eyebrow">TASK DETAIL</span><span className="version">v{task.version}</span></div><h2>{task.name}</h2><div className="detail-sub"><StatusBadge status={task.status}/>{snapshot.role === 'admin' && <button className="button small" onClick={onEdit}><Icon name="edit" size={15}/>编辑任务</button>}</div></div>
    <div className="detail-tabs" role="tablist" aria-label="详情分类">{([['brief', '任务说明'], ['context', '工作上下文'], ['changes', `变更 ${notices.length}`]] as const).map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} aria-controls={`detail-${key}`} id={`tab-${key}`} onClick={() => setTab(key)}>{label}</button>)}</div>
    <div className="detail-body" role="tabpanel" id={`detail-${tab}`} aria-labelledby={`tab-${tab}`}>
      {tab === 'brief' && <><TextBlock title="任务目标" value={task.goal}/><TextBlock title="验收标准" value={task.acceptance}/>
        <div className="metadata"><div><span>执行者</span><strong>{task.executor || '尚未分配'}</strong></div><div><span>Git 分支</span><code>{task.branch || '尚未关联'}</code></div><div><span>进度</span><strong>{task.progress}%</strong></div></div>
        <section className="text-block"><h3>任务关系</h3><div className="relation-label">依赖于</div><div className="task-links">{task.dependencies.length ? task.dependencies.map(taskLink) : <span className="muted">没有前置依赖</span>}</div><div className="relation-label">被依赖</div><div className="task-links">{dependents.length ? dependents.map(t => taskLink(t.task_id)) : <span className="muted">没有后续依赖</span>}</div>{task.parent_id && <><div className="relation-label">父任务</div>{taskLink(task.parent_id)}</>}</section>
        <TextBlock title="公开接口契约" value={task.contract}/><TextBlock title="详细描述" value={task.description}/><TextBlock title="技术约束" value={task.constraints}/>
        <div className="detail-foot"><code>{task.task_id}</code><span>更新于 {formatTime(task.updated_at)}</span></div>
      </>}
      {tab === 'context' && <><p className="context-info">由任务执行者维护 · 上下文 v{context?.version ?? '—'}</p>{context ? (Object.entries({ summary: '当前摘要', completed: '已完成工作', todos: '待办事项', blockers: '阻塞与问题', next_steps: '下一步', decisions: '任务内部决策', failed_attempts: '失败尝试', git_notes: 'Git 工作记录' }) as [keyof typeof context.data, string][]).map(([key, title]) => <TextBlock key={key} title={title} value={context.data[key]}/>) : <p className="muted">暂无工作上下文。</p>}</>}
      {tab === 'changes' && <><p className="context-info">由任务执行者确认和报告修改完成，与任务进度分别记录。</p>{notices.length ? notices.map(n => <NotificationCard key={n.id} item={n}/>) : <p className="muted">该任务还没有变更通知。</p>}</>}
    </div>
  </aside>;
}

export default function App() {
  const [token, setToken] = useState(storedToken);
  const activeToken = useRef(token); activeToken.current = token;
  const remember = useRef(!!token);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [authBusy, setAuthBusy] = useState(!!token);
  const [authError, setAuthError] = useState<ApiError | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState(() => location.hash.slice(1));
  const [editor, setEditor] = useState<Task | 'new' | null>(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState<'tasks' | 'notifications'>('tasks');
  const [noticeFilter, setNoticeFilter] = useState('all');
  const [success, setSuccess] = useState('');
  const [lastLoaded, setLastLoaded] = useState('');

  function select(id: string) { setSelected(id); history.replaceState(null, '', id ? `#${id}` : location.pathname); }
  function accept(next: Snapshot) {
    setSnapshot(next); setLastLoaded(new Date().toISOString());
    setSelected(current => next.tasks.some(t => t.task_id === current) ? current : next.tasks[0]?.task_id || '');
  }
  function logout(expired = false) {
    activeToken.current = ''; rememberToken(''); setToken(''); setSnapshot(null); setEditor(null); setError(null); setSuccess(''); setAuthBusy(false);
    setAuthError(expired ? new ApiError(401, 'unauthorized', '令牌已失效，请重新连接。') : null);
  }

  useEffect(() => {
    if (!token) return;
    let active = true;
    setAuthBusy(true); setAuthError(null);
    checkHealth().then(() => {
      if (!active) return null;
      return call<Snapshot>(token, 'snapshot');
    }).then(next => {
      if (!active || !next) return;
      accept(next); rememberToken(remember.current ? token : '');
    }).catch(err => {
      if (!active) return;
      const problem = asError(err);
      if (problem.status === 403) problem.message = '当前令牌不能查看控制台。请使用管理员、协调者或审核者令牌。';
      setAuthError(problem); rememberToken(''); setToken('');
    }).finally(() => { if (active) setAuthBusy(false); });
    return () => { active = false; };
  }, [token]);

  async function refresh() {
    const forToken = token;
    setRefreshing(true); setError(null);
    try { await checkHealth(); if (activeToken.current !== forToken) return; const next = await call<Snapshot>(token, 'snapshot'); if (activeToken.current === forToken) accept(next); }
    catch (err) { if (activeToken.current === forToken) { const problem = asError(err); setError(problem); if (problem.status === 401) logout(true); } }
    finally { if (activeToken.current === forToken) setRefreshing(false); }
  }

  async function saved(result: TaskResult) {
    setEditor(null); setQuery(''); setFilter('all'); select(result.task.task_id);
    setSuccess(`已保存「${result.task.name}」 · 项目 v${result.project_version} · 已生成 ${result.affected_tasks.length} 个任务的变更通知`);
    // Show only data returned by the successful write while obtaining the latest full snapshot.
    setSnapshot(current => current ? { ...current, tasks: current.tasks.some(t => t.task_id === result.task.task_id)
      ? current.tasks.map(t => t.task_id === result.task.task_id ? result.task : t) : [...current.tasks, result.task] } : current);
    await refresh();
  }

  if (!snapshot) return <Login busy={authBusy} error={authError} onConnect={(value, save) => { remember.current = save; setAuthBusy(true); setToken(value); }}/>;
  const visible = snapshot.tasks.filter(t => (filter === 'all' || t.status === filter) && `${t.name} ${t.goal} ${t.executor} ${t.task_id}`.toLowerCase().includes(query.toLowerCase()));
  const currentTask = snapshot.tasks.find(t => t.task_id === selected);
  const pending = snapshot.notifications.filter(n => n.status !== 'completed').length;
  const active = snapshot.tasks.filter(t => t.status === 'in_progress').length;
  const done = snapshot.tasks.filter(t => t.status === 'done').length;
  const displayedNotices = snapshot.notifications.filter(n => noticeFilter === 'all' || n.status === noticeFilter);

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#" onClick={e => { e.preventDefault(); setPage('tasks'); }}><span className="brand-mark">r</span>relay</a><span className="sidebar-caption">团队协作空间</span>
      <div className="project-card"><span className="project-symbol"><Icon name="branch"/></span><div><strong>{snapshot.project.name}</strong><small>项目 v{snapshot.project.version}</small></div></div>
      <div className="nav-label">工作空间</div><nav aria-label="主导航"><button className={page === 'tasks' ? 'active' : ''} onClick={() => setPage('tasks')}><Icon name="grid"/>任务空间<span>{snapshot.tasks.length}</span></button><button className={page === 'notifications' ? 'active' : ''} onClick={() => setPage('notifications')}><Icon name="bell"/>变更通知{pending > 0 && <span>{pending}</span>}</button></nav>
      <div className="sidebar-bottom"><div className="live-status"><span className={`dot ${error ? 'connection-error' : ''}`}/>{error ? '同步失败 · 显示上次数据' : '真实后台已连接'}</div><div className="profile"><div className="avatar">{snapshot.role === 'admin' ? '管' : '阅'}</div><div><strong>{snapshot.role === 'admin' ? '项目管理员' : snapshot.role === 'coordinator' ? '协调者' : '审核者'}</strong><small>{snapshot.role === 'admin' ? '任务规划与协作' : '只读访问'}</small></div><button className="icon-button" aria-label="退出登录" onClick={() => logout()}><Icon name="logout" size={17}/></button></div></div>
    </aside>
    <main className="workspace"><header className="topbar"><div className="breadcrumb">工作空间<span>/</span><strong>{page === 'tasks' ? '任务空间' : '变更通知'}</strong></div><div className="topbar-actions"><span className="sync-time">{lastLoaded && `${formatTime(lastLoaded)} 已同步`}</span><button className="button small" onClick={refresh} disabled={refreshing}><Icon name="refresh" size={16}/>{refreshing ? '同步中…' : '刷新数据'}</button></div></header>
      <div className="workspace-content"><div className="page-heading"><div><span className="eyebrow">{page === 'tasks' ? 'TEAM WORKSPACE' : 'CHANGE TRACKING'}</span><h1>{page === 'tasks' ? '让任务清晰，让协作发生。' : '每一次变更，都有回应。'}</h1><p>{page === 'tasks' ? snapshot.project.goal || '定义目标、连接依赖，在同一份上下文上持续推进。' : '查看正式变更的影响范围，跟踪理解与修改进度。'}</p></div>{page === 'tasks' && snapshot.role === 'admin' && <button className="button primary" onClick={() => setEditor('new')}><Icon name="plus" size={18}/>新建任务</button>}</div>
        <ErrorNotice error={error}/>{success && <div className="success-banner" role="status"><Icon name="check" size={18}/><span>{success}</span><button className="icon-button" aria-label="关闭保存提示" onClick={() => setSuccess('')}><Icon name="close" size={16}/></button></div>}
        <div className="stats"><div><span className="stat-icon lavender"><Icon name="grid"/></span><div><small>全部任务</small><strong>{snapshot.tasks.length}<span>项</span></strong></div></div><div><span className="stat-icon blue"><Icon name="arrow"/></span><div><small>正在推进</small><strong>{active}<span>项</span></strong></div></div><div><span className="stat-icon green"><Icon name="check"/></span><div><small>已经完成</small><strong>{done}<span>项</span></strong></div></div><div><span className="stat-icon orange"><Icon name="bell"/></span><div><small>待处理变更</small><strong>{pending}<span>条</span></strong></div></div></div>
        {page === 'tasks' ? <div className={`task-layout ${currentTask ? '' : 'without-detail'}`}><section className="task-list-panel" aria-label="任务列表"><div className="list-heading"><h2>全部任务 <span>{visible.length}</span></h2><span className="muted">目标驱动 · 自由拆分</span></div>
          <div className="list-toolbar"><label className="search-field"><Icon name="search" size={17}/><input aria-label="搜索任务" placeholder="搜索任务、目标或执行者" value={query} onChange={e => setQuery(e.target.value)}/></label><select aria-label="筛选任务状态" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部状态</option>{Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
          {visible.length ? <div className="task-list">{visible.map((task, index) => <button type="button" key={task.task_id} className={`task-row ${selected === task.task_id ? 'selected' : ''}`} aria-pressed={selected === task.task_id} onClick={() => select(task.task_id)} data-testid="task-row"><div className="task-row-top"><span className="task-index">{String(index + 1).padStart(2, '0')}</span><StatusBadge status={task.status}/><span className="task-percent">{task.progress}%</span></div><h3>{task.name}</h3><p className="task-goal">{task.goal}</p><div className="progress-track"><span style={{ width: `${task.progress}%` }}/></div><div className="task-row-bottom"><span className="executor"><span className="tiny-avatar">{task.executor.trim().slice(0, 1) || '—'}</span>{task.executor || '尚未分配'}</span><span className="dependency-count"><Icon name="branch" size={14}/>{task.dependencies.length ? `${task.dependencies.length} 项依赖` : '独立任务'}<Icon name="arrow" size={14}/></span></div></button>)}</div>
            : <div className="empty-state"><span className="empty-icon"><Icon name="grid" size={30}/></span><h3>{snapshot.tasks.length ? '没有匹配的任务' : '从第一项任务开始'}</h3><p>{snapshot.tasks.length ? '试试其他关键词或状态筛选。' : '把一个明确目标交给一个任务，让团队从这里开始协作。'}</p>{snapshot.tasks.length ? <button className="button" onClick={() => { setQuery(''); setFilter('all'); }}>清除筛选</button> : snapshot.role === 'admin' && <button className="button primary" onClick={() => setEditor('new')}><Icon name="plus" size={16}/>创建第一项任务</button>}</div>}
        </section>{currentTask && <TaskDetail key={currentTask.task_id} task={currentTask} snapshot={snapshot} onSelect={select} onEdit={() => setEditor(currentTask)}/>}</div>
          : <section className="notifications-panel"><div className="list-heading"><h2>变更记录 <span>{displayedNotices.length}</span></h2><select aria-label="筛选通知状态" value={noticeFilter} onChange={e => setNoticeFilter(e.target.value)}><option value="all">全部通知</option>{Object.entries(notificationLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></div><p className="context-info">通知的确认和完成由各任务执行者报告。任务进度不会因为通知送达而自动改变。</p><div className="notification-grid">{displayedNotices.map(item => <NotificationCard key={item.id} item={item} taskName={snapshot.tasks.find(t => t.task_id === item.task_id)?.name} onSelect={() => { setPage('tasks'); select(item.task_id); }}/>)}</div>{!displayedNotices.length && <div className="empty-state"><Icon name="bell" size={30}/><h3>暂无此类通知</h3><p>创建或调整任务后，后台会生成对应的变更记录。</p></div>}</section>}
        <footer className="workspace-footer"><span>RELAY / 围绕任务持续协作</span><span>任务状态与变更状态分别记录</span></footer>
      </div>
    </main>
    {editor && <TaskEditor task={editor === 'new' ? null : editor} tasks={snapshot.tasks} token={token} onClose={() => setEditor(null)} onSaved={saved} onSnapshot={accept} onExpired={() => logout(true)}/>}
  </div>;
}

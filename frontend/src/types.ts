// Shared v0.1 shapes from contracts/responses.py and contracts/requests.py.
// No backend permission or transition logic is replicated here.
export type TaskStatus = 'todo' | 'in_progress' | 'in_review' | 'done' | 'blocked';
export interface TaskFields {
  name: string;
  goal: string;
  description: string;
  acceptance: string;
  contract: string;
  constraints: string;
  dependencies: string[];
  parent_id: string | null;
  executor: string;
  branch: string;
}
export interface Task extends TaskFields {
  task_id: string;
  status: TaskStatus;
  progress: number;
  version: number;
  archived: 0 | 1;
  created_at: string;
  updated_at: string;
}
export interface TaskContext {
  task_id: string;
  version: number;
  updated_at: string;
  data: Record<'summary' | 'completed' | 'todos' | 'blockers' | 'decisions' | 'failed_attempts' | 'next_steps' | 'git_notes', string>;
}
export interface Notification {
  id: string;
  decision_id: string;
  task_id: string;
  project_version: number;
  status: 'pending' | 'acknowledged' | 'completed';
  note: string;
  title: string;
  body: string;
  created_at: string;
  acknowledged_at: string | null;
  completed_at: string | null;
}
export interface Snapshot {
  role: 'admin' | 'coordinator' | 'reviewer';
  project: { id: 1; name: string; goal: string; private_context: string; guidance: string; version: number; updated_at: string };
  tasks: Task[];
  contexts: Record<string, TaskContext>;
  notifications: Notification[];
}
export interface ChangeEvent { decision_id: string; project_version: number; affected_tasks: string[] }
export interface TaskResult extends ChangeEvent { task: Task }

export const statusLabels: Record<TaskStatus, string> = {
  todo: '待开始', in_progress: '进行中', in_review: '待审核', done: '已完成', blocked: '阻塞',
};
export const notificationLabels = { pending: '待确认', acknowledged: '已确认理解', completed: '已完成修改' };

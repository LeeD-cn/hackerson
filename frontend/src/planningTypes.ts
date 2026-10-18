import type { Task, TaskFields } from './types';

export interface PlannedTask extends TaskFields { key: string; handoff_prompt: string }
export interface PlanContent { reply: string; tasks: PlannedTask[] }
export interface PlanningDraft {
  draft_id: string;
  version: number;
  status: 'draft' | 'applied';
  base_project_version: number;
  plan: PlanContent;
  messages: { role: 'user' | 'assistant'; content: string }[];
  created_at: string;
  updated_at: string;
}
export interface DraftSummary {
  draft_id: string; version: number; status: 'draft' | 'applied'; base_project_version: number;
  reply: string; task_count: number; created_at: string; updated_at: string;
}
export interface AppliedPlan {
  draft_id: string; version: number; project_version: number;
  task_ids: Record<string, string>; tasks: Task[];
}

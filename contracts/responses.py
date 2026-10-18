"""Shared v0.1 response shapes. These types do not implement business behavior."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .requests import Status


class Output(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Project(Output):
    id: Literal[1]
    name: str
    goal: str
    private_context: str
    guidance: str
    version: int = Field(ge=1)
    updated_at: str


class TaskSummary(Output):
    task_id: str
    name: str
    status: Status
    progress: int = Field(ge=0, le=100)
    dependencies: list[str]
    parent_id: str | None
    version: int = Field(ge=1)


class TaskDetail(TaskSummary):
    goal: str
    description: str
    acceptance: str
    contract: str
    constraints: str
    executor: str
    branch: str
    archived: Literal[0, 1]
    created_at: str
    updated_at: str


class ContextData(Output):
    summary: str
    completed: str
    todos: str
    blockers: str
    decisions: str
    failed_attempts: str
    next_steps: str
    git_notes: str


class TaskContext(Output):
    task_id: str
    version: int = Field(ge=1)
    data: ContextData
    updated_at: str


class PublicContract(Output):
    task_id: str
    name: str
    contract: str
    version: int = Field(ge=1)


class QueryModuleResponse(Output):
    contract: PublicContract
    query_id: str
    mode: Literal['published_contract']
    notice: str


class ErrorDetail(Output):
    field: str
    message: str


class ErrorBody(Output):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(Output):
    error: ErrorBody


class MessageRecord(Output):
    id: str
    sender: str
    target: str
    kind: Literal['message', 'query', 'contract_response', 'status']
    body: str
    reply_to: str | None
    created_at: str


class ChangeRequest(Output):
    id: str
    proposer: str
    task_id: str
    title: str
    rationale: str
    patch: dict
    base_version: int = Field(ge=1)
    status: Literal['pending', 'approved', 'rejected']
    review_note: str
    reviewed_by: str | None
    created_at: str
    reviewed_at: str | None


class Decision(Output):
    id: str
    project_version: int = Field(ge=1)
    task_id: str | None
    title: str
    body: str
    actor: str
    change_id: str | None
    created_at: str


class Notification(Output):
    id: str
    decision_id: str
    task_id: str
    project_version: int = Field(ge=1)
    status: Literal['pending', 'acknowledged', 'completed']
    note: str
    created_at: str
    acknowledged_at: str | None
    completed_at: str | None
    title: str
    body: str


class SubmissionRecord(Output):
    id: str
    task_id: str
    commit_sha: str
    branch: str
    summary: str
    test_results: str
    status: Literal['pending', 'approved', 'changes_requested', 'integrated']
    feedback: str
    reviewer: str | None
    integration_commit: str | None
    integration_note: str | None
    created_at: str
    reviewed_at: str | None


class ChangeEvent(Output):
    decision_id: str
    project_version: int = Field(ge=1)
    affected_tasks: list[str]


class BootstrapContext(Output):
    project_version: int = Field(ge=1)
    guidance: str
    task: TaskDetail
    context: TaskContext
    dependency_contracts: list[PublicContract]
    decisions: list[Decision]
    notifications: list[Notification]
    messages: list[MessageRecord]
    submissions: list[SubmissionRecord]
    instructions: str


class Snapshot(Output):
    project: Project
    tasks: list[TaskDetail]
    contexts: dict[str, TaskContext]
    messages: list[MessageRecord]
    changes: list[ChangeRequest]
    notifications: list[Notification]
    decisions: list[Decision]
    submissions: list[SubmissionRecord]
    role: Literal['admin', 'coordinator', 'reviewer']

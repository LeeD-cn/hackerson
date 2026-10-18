"""Shared v0.1 request contracts. No API routes or business implementation."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Status = Literal['todo', 'in_progress', 'in_review', 'done', 'blocked']


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Empty(Input):
    pass


class TaskId(Input):
    task_id: str = Field(min_length=1, max_length=80)


class TaskFields(Input):
    name: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=10000)
    description: str = Field(default='', max_length=20000)
    acceptance: str = Field(default='', max_length=20000)
    contract: str = Field(default='', max_length=30000)
    constraints: str = Field(default='', max_length=20000)
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    parent_id: str | None = None
    executor: str = Field(default='', max_length=200)
    branch: str = Field(default='', max_length=500)


class TaskPatch(Input):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    goal: str | None = Field(default=None, min_length=1, max_length=10000)
    description: str | None = Field(default=None, max_length=20000)
    acceptance: str | None = Field(default=None, max_length=20000)
    contract: str | None = Field(default=None, max_length=30000)
    constraints: str | None = Field(default=None, max_length=20000)
    dependencies: list[str] | None = Field(default=None, max_length=100)
    parent_id: str | None = None
    executor: str | None = Field(default=None, max_length=200)
    branch: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def reject_nulls(self):
        for key in self.model_fields_set - {'parent_id'}:
            if getattr(self, key) is None:
                raise ValueError(f'{key} cannot be null')
        if not self.model_fields_set:
            raise ValueError('patch must contain at least one field')
        return self


class EditTask(TaskId):
    expected_version: int = Field(ge=1)
    patch: TaskPatch
    reason: str = Field(min_length=1, max_length=5000)


class DeleteTask(TaskId):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=5000)


class ProjectEdit(Input):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    goal: str = Field(default='', max_length=20000)
    private_context: str = Field(default='', max_length=40000)
    guidance: str = Field(default='', max_length=20000)
    reason: str = Field(min_length=1, max_length=5000)


class ContextUpdate(Input):
    expected_version: int = Field(ge=1)
    summary: str | None = Field(default=None, max_length=30000)
    completed: str | None = Field(default=None, max_length=30000)
    todos: str | None = Field(default=None, max_length=30000)
    blockers: str | None = Field(default=None, max_length=20000)
    decisions: str | None = Field(default=None, max_length=20000)
    failed_attempts: str | None = Field(default=None, max_length=20000)
    next_steps: str | None = Field(default=None, max_length=20000)
    git_notes: str | None = Field(default=None, max_length=20000)


class StatusUpdate(Input):
    expected_version: int = Field(ge=1)
    status: Status
    progress: int = Field(ge=0, le=100)
    note: str = Field(default='', max_length=5000)

    @model_validator(mode='after')
    def completed_progress(self):
        if self.status == 'done' and self.progress != 100:
            raise ValueError('done requires progress=100')
        return self


class QueryModule(TaskId):
    question: str = Field(default='', max_length=5000)


class Message(Input):
    target: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=20000)
    reply_to: str | None = None


class Proposal(TaskId):
    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=10000)
    expected_project_version: int = Field(ge=1)
    patch: TaskPatch


class Approval(Input):
    change_id: str
    approve: bool
    note: str = Field(min_length=1, max_length=10000)


class NotificationUpdate(Input):
    notification_id: str
    status: Literal['acknowledged', 'completed']
    note: str = Field(min_length=1, max_length=5000)


class Submission(Input):
    commit: str = Field(pattern=r'^[0-9a-fA-F]{40}$')
    branch: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=20000)
    test_results: str = Field(min_length=1, max_length=20000)


class Review(Input):
    submission_id: str
    verdict: Literal['approved', 'changes_requested']
    feedback: str = Field(min_length=1, max_length=20000)


class Credential(Input):
    role: Literal['coordinator', 'reviewer']


class Integration(Input):
    submission_id: str
    integration_commit: str = Field(pattern=r'^[0-9a-fA-F]{40}$')
    note: str = Field(min_length=1, max_length=10000)

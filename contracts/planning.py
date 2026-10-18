"""Web coordinator contracts, separate from the task MCP tool contracts."""
from typing import Literal

from pydantic import Field, model_validator

from .requests import Input, TaskFields
from .responses import Output, TaskDetail


class PlannedTask(TaskFields):
    # Local keys cannot be confused with persisted task_<uuid> identities.
    key: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,47}$', description='Local key; must not start with task_')
    handoff_prompt: str = Field(min_length=1, max_length=16000)

    @model_validator(mode='after')
    def local_key(self):
        if self.key.startswith('task_'):
            raise ValueError('Local keys must not start with task_')
        return self


class PlanContent(Input):
    reply: str = Field(min_length=1, max_length=10000)
    tasks: list[PlannedTask] = Field(default_factory=list, max_length=30)


class PlanningChat(Input):
    message: str = Field(min_length=1, max_length=12000)
    draft_id: str | None = Field(default=None, min_length=1, max_length=80)
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode='after')
    def revision_requires_version(self):
        if (self.draft_id is None) != (self.expected_version is None):
            raise ValueError('draft_id and expected_version must be supplied together')
        return self


class PlanningVersion(Input):
    expected_version: int = Field(ge=1)


class PlanningEdit(PlanningVersion):
    plan: PlanContent


class PlanningMessage(Output):
    role: Literal['user', 'assistant']
    content: str


class PlanningDraftSummary(Output):
    draft_id: str
    version: int
    status: Literal['draft', 'applied']
    base_project_version: int
    reply: str
    task_count: int
    created_at: str
    updated_at: str


class PlanningDraft(Output):
    draft_id: str
    version: int
    status: Literal['draft', 'applied']
    base_project_version: int
    plan: PlanContent
    messages: list[PlanningMessage]
    created_at: str
    updated_at: str


class AppliedPlan(Output):
    draft_id: str
    version: int
    project_version: int
    task_ids: dict[str, str]
    tasks: list[TaskDetail]

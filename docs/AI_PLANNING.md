# 网页主 Agent 1：任务规划后端

本批交付后端与共享类型；网页聊天、草案展示及确认按钮由前端接入。现有 MCP 工具不受影响。
主流程：管理员提出需求 → 外部模型生成完整任务草案 → 对话或人工修改 → 管理员确认 → 同一事务创建全部任务。
首次能力只新增任务；不会自动修改、删除已有任务，不启动开发 AI，不审核或合并代码。

## 本地模型配置

不新增依赖，使用现有 httpx。配置模板已按用户指定的平台和模型填写：

```powershell
New-Item -ItemType Directory -Force .local/planning
Copy-Item backend/planning.example.json .local/planning/settings.json
notepad .local/planning/api-key.txt
```

最后一步只在本地文件中填写真实密钥并保存，不将密钥发到聊天、终端参数或 Git。
文件已被 `.local/` 忽略。不要覆盖已有配置或密钥文件。

```powershell
.\scripts\start_planner.ps1
```

默认监听 `http://127.0.0.1:8765`，使用 `data/relay.db`。先停止占用同端口的旧后端。
如使用 `-Port 8780 -Database data/planning.db`，前端也必须连接该服务；独立数据库不含原来的任务。
管理员身份仍使用后端 `.local/admin-token.txt` 或 `RELAY_ADMIN_TOKEN`，与模型 API 密钥不同。

模板：`base_url=https://llmapi.paratera.com`，`model=DeepSeek-V4-Pro-0813`。
适配器将裸主机地址规范化为 `/v1/chat/completions`；若基础地址已经包含 `/v1`，不重复追加。
也可配置其他提供商的 API 根路径。请求结构参考 [Chat Completions 官方协议](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。
用户提供的 [平台文档](https://ai.paratera.com/document/llm) 尚未通过本次文档抓取验证；平台实际路径、模型权限与输出兼容性需真实调用确认。
为避免未经确认的 JSON 模式兼容性要求，模板 `json_mode=false`；模型仍被要求生成 JSON，后端始终严格校验。
供应商明确支持时可设为 true，发送 `response_format={"type":"json_object"}`。

直接环境变量方式：`RELAY_AI_BASE_URL`、`RELAY_AI_MODEL`、`RELAY_AI_API_KEY_FILE`（或 `RELAY_AI_API_KEY`）、
`RELAY_AI_JSON_MODE`（默认 1）、`RELAY_AI_TIMEOUT_SECONDS`（默认 60，范围 1–180 秒）。
不自动读取 .env；不自动重试模型请求；不跟随重定向；不读取系统代理。

管理员明确发起规划时，会将当前项目配置（含私有项目说明）、未归档任务与私有进度、最近 20 条决策、
本草案对话发送给配置的外部模型。不发送凭据表、管理员令牌或模型密钥作为对话内容。

## 前端接口

统一携带 `Authorization: Bearer <管理员令牌>`。首版仅管理员可访问全部规划接口；
任务/coordinator/reviewer 令牌不可读取规划对话。错误沿用 `error.code/message/details`。
共享类型：`contracts/planning.py`。新增可重入表：`contracts/planning.sql`；启动时自动创建，保留原有数据和 v0.1 表。

### 1. 新建或继续对话

`POST /api/planning/chat`

```json
{"message":"我们三个人、剩两小时，要开发活动报名系统，请划分任务并生成交接提示词。"}
```

继续同一草案时必须同时提供 `draft_id` 和当前草案 `expected_version`：

```json
{"message":"名单导出先不做，按已有开发进度调整", "draft_id":"plan_…", "expected_version":1}
```

响应为 `PlanningDraft`，主要结构：

```json
{
  "draft_id":"plan_…",
  "version":1,
  "status":"draft",
  "base_project_version":1,
  "plan":{
    "reply":"建议先实现报名接口，再开发页面。",
    "tasks":[
      {"key":"api","name":"报名接口","goal":"接收报名", "handoff_prompt":"读取任务上下文，核对代码，实现并测试接口。"},
      {"key":"page","name":"报名页面","goal":"提交报名", "dependencies":["api"], "handoff_prompt":"查询依赖公开契约，实现页面并保存进度。"}
    ]
  },
  "messages":[{"role":"user","content":"…"},{"role":"assistant","content":"完整草案 JSON 字符串"}],
  "created_at":"UTC 时间",
  "updated_at":"UTC 时间"
}
```

上例 tasks 省略的可选字段会在实际响应中补全默认值；完整字段与 `TaskFields` 一致，另有 `key/handoff_prompt`。
`key` 是当前草案局部标识（小写字母开头、最长 48 位、不能以 task_ 开头）。
`dependencies`/`parent_id` 可引用本草案 key 或已有 task_id；父子与依赖合并后必须无环。
生成的是完整替换草案，不是增量。信息不足时 `tasks=[]`，在 reply 中提问，此时不能确认。
前端等待时间应长于配置的模型超时；加载期间阻止重复发送，不自动重试 POST。

### 2. 找回对话

`GET /api/planning/drafts`：`{"drafts":[PlanningDraftSummary]}`，最近更新的 50 份。

`GET /api/planning/drafts/{draft_id}`：完整 `PlanningDraft`，重启后仍可恢复。

### 3. 人工编辑完整草案

`PUT /api/planning/drafts/{draft_id}`

```json
{"expected_version":1, "plan":{"reply":"调整为两项任务", "tasks":[{"key":"api","name":"报名接口","goal":"接收报名","handoff_prompt":"核对已有代码后继续开发。"}]}}
```

成功返回更新后的 `PlanningDraft`，version 加 1，不创建正式任务。完整替换 plan，支持在页面编辑或删除草案条目。

### 4. 用户确认创建

`POST /api/planning/drafts/{draft_id}/confirm`

```json
{"expected_version":2}
```

响应 `AppliedPlan` 包含 `draft_id`、递增后的草案 `version`、最新 `project_version`、
草案 key 到正式 task_id 的映射 `task_ids`，以及完整 `TaskDetail` 对象数组 `tasks`。

全部任务、依赖、初始上下文、历史、决策通知和草案确认状态在同一事务中提交；任一步失败全部回滚。
交接提示词保存在新任务上下文 `data.next_steps`，上下文版本为 2，开发 AI 可通过现有 `get_my_context` 读取。
不自动签发任务令牌；管理员仍通过 `issue_task_token` 分配任务身份。
同一确认请求重复发送（使用原来的 expected_version）返回首次保存的结果，不重复建任务。
已确认草案不能继续编辑或生成，开启新的规划即可。
确认成功后前端刷新现有 snapshot 和任务列表。

## 冲突与失败

- 草案版本过期：409 `version_conflict`。重新读取草案后再操作。
- 项目或任何任务上下文/状态已变化：409 `planning_project_changed`。继续该草案对话，按最新进度重新规划，再人工确认。
  进度变化也会阻止旧草案，即使项目版本未改变。生成期间发生变化则丢弃本轮结果，不保存半次对话。
- 无配置：503 `ai_not_configured`；模型鉴权失败：502 `ai_auth_failed`。
- 连接失败：502 `ai_unavailable`；超时：504 `ai_timeout`；限流：503 `ai_rate_limited`。
- 上游错误：502 `ai_upstream_error`；不完整/错误 JSON 或字段：502 `ai_invalid_response`；引用/循环错误：502 `ai_invalid_plan`。
- 手工编辑引用无效或确认空任务草案：422 `invalid_plan`。
- 草案不存在：404 `planning_draft_not_found`；已确认后编辑：409 `planning_already_applied`（版本正确时）。
- 限制：每份草案最多 30 个新任务、20 轮模型对话；项目上下文 18 万字符、模型输入 35 万字符。
  超限返回 422 `planning_context_too_large` 或 `planning_history_limit`，不静默丢弃已有上下文。
- 模型失败不会回退成虚构规划，不返回供应商原始错误、请求头或密钥。

## 本批验证范围

按用户要求做简要测试：完整草案/修改/确认/重复确认/重启恢复、事务失败回滚、模型请求协议、本地密钥文件、无配置报错。
使用测试模型与模拟模型 HTTP 响应；没有真实供应商调用结果，也未验证新增前端界面。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_planning.py -q -k 'full_workflow or failure_mid_confirmation or model_protocol or unconfigured_provider' --basetemp=.tmp/planning-simple -p no:cacheprovider
```

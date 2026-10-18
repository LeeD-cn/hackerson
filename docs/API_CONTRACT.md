# HTTP / MCP 接口契约 v0.1

状态：共享契约。后端已提供 P0 HTTP 接口；BE-02 补齐跨模块查询和错误响应类型及上下文更新语义。各模块实际可用能力以对应分支和验证记录为准。

## 统一入口

MVP 使用一个简单的命令式 HTTP 入口，避免为 MCP 和页面重复维护两套业务接口：

```text
POST /api/tools/{action}
Authorization: Bearer <token>
Content-Type: application/json

请求体：该 action 的参数对象
成功：HTTP 200 + JSON 对象
```

`GET /health` 返回 `{"status":"ok","version":"0.1.0"}`；不包含业务数据。`GET /api/tool-schemas` 可返回输入 JSON Schema。接口 schema 不是访问授权。

本地地址约定为 `http://127.0.0.1:8765`。B 的 `RELAY_API_URL` 只包含该 origin，不重复附加 `/api`。跨电脑连接时改成后台可访问地址；局域网监听、防火墙、HTTPS 由 A 部署时配置，不自动开放公网。

前端开发时建议由开发服务器代理 `/api` 到后台，不默认启用任意来源的跨域访问。

## 共享输入与主要输出

下面的输入类都在 `contracts/requests.py`。类定义及其 JSON Schema 是字段的精确依据，额外字段禁止。`TaskPatch` 与 `ContextUpdate` 的 null 规则不同，见下方更新语义。

| action | 输入类 | 输出 | 权限／优先级 |
| --- | --- | --- | --- |
| `snapshot` | `Empty` | `{project, tasks, contexts, messages, changes, notifications, decisions, submissions, role}` | 管理员、两主角色；P0，供控制台查看 |
| `edit_project` | `ProjectEdit` | `ChangeEvent` | 管理员；P0 |
| `create_task` | `TaskFields` | `{task, ...ChangeEvent}` | 管理员；P0 |
| `edit_task` | `EditTask` | `{task, ...ChangeEvent}` | 管理员；P0 |
| `delete_task` | `DeleteTask` | `ChangeEvent`，实际归档 | 管理员；P0 |
| `issue_task_token` | `TaskId` | `{token, role, task_id, notice}` | 管理员；P0，原文仅返回一次，旧令牌撤销 |
| `list_tasks` | `Empty` | `{tasks: TaskSummary[], project_version}` | 所有身份；P0 |
| `get_task_status` | `TaskId` | `TaskSummary` | 所有身份；P0 |
| `get_my_context` | `Empty` | `BootstrapContext` | 子任务；P0 |
| `update_my_context` | `ContextUpdate` | `TaskContext` | 子任务，仅本人；P0 |
| `report_status` | `StatusUpdate` | `TaskSummary` | 子任务，仅本人；P0 |
| `query_module` | `QueryModule` | `QueryModuleResponse` | 所有身份；P0 |
| `send_message` | `Message` | `MessageRecord` | 所有身份；P0 |
| `get_messages` | `Empty` | `{messages: MessageRecord[]}` | 子任务仅本人收发，主角色全局；P0 |
| `propose_change` | `Proposal` | `{change_id, status: "pending", affected_tasks}` | 子任务、协调者、管理员；P0 最小提案 |
| `list_changes` | `Empty` | `{changes: ChangeRequest[]}` | 子任务仅本人提出或本人目标，主角色全局；P0 |
| `review_change` | `Approval` | `{change_id, status, ...ChangeEvent}`；拒绝无 ChangeEvent | 仅管理员；P0 人工生效入口 |
| `get_notifications` | `Empty` | `{notifications: Notification[]}` | 子任务仅本人，主角色全局；P0 |
| `acknowledge_change` | `NotificationUpdate` | `Notification` | 子任务仅本人；P0 |
| `get_project_context` | `Empty` | `Project` | 管理员、两主角色；P1 |
| `get_task_context` | `TaskId` | `{task, context}` | 管理员、两主角色；P1 |
| `issue_role_token` | `Credential` | `{token, role, task_id: null, notice}` | 管理员；P1 |
| `submit_change` | `Submission` | `{submission_id, status, notice}` | 子任务；P1 |
| `get_review_feedback` | `Empty` | `{submissions: SubmissionRecord[]}` | 子任务仅本人，主角色全局；P1 |
| `review_submission` | `Review` | `SubmissionRecord` | 管理员、审核主角色；P1 |
| `record_integration` | `Integration` | `SubmissionRecord` | 管理员、审核主角色；P1，只登记外部 Git 结果 |

P1 未实现时，`snapshot.submissions` 返回空列表；不能用虚构数据代替。P1 字段保留是为了避免后续改变结构，不要求这轮全部实现。

## 输出形状

详细类型在 `contracts/responses.py`，可直接用于 FastAPI 的响应模型；MCP 以对象或 JSON 文本返回同样内容。页面以同样字段定义 TypeScript 类型。

- `TaskSummary` 只有 `task_id/name/status/progress/parent_id/dependencies/version`，不含私有上下文和完整任务描述。
- `TaskDetail` 在其基础上包含目标、描述、验收、发布接口、约束、执行者、分支、归档标记和时间。
- `TaskContext` 为 `{task_id, version, data, updated_at}`，`data` 为八个固定文本字段。
- `PublicContract` 只有 `task_id/name/contract/version`。
- `QueryModuleResponse` 为 `{contract: PublicContract, query_id: str, mode: "published_contract", notice: str}`。
- `BootstrapContext` 包含当前 `project_version`、授权摘要 `guidance`、本人任务及私有上下文、必要依赖接口、相关决策、本人通知/消息/提交及接手提示；不包含全局私有上下文。
- `ChangeEvent` 包含 `decision_id/project_version/affected_tasks`。
- `snapshot.contexts` 是以 `task_id` 为键的对象；不是数组。

`query_module` 的 MVP 行为：记录查询并返回目标已发布契约，`mode="published_contract"`。问题若超出契约，由协调者通过消息回复；不要声称模型已经理解并解答问题。

`messages.sender/target` 使用任务 ID 或保留身份 `admin/coordinator/reviewer`；sender 由服务端生成，不信任客户端自报。用户不得通过 `reply_to` 引用无权读取的消息。

## 示例：恢复和更新

```http
POST /api/tools/get_my_context
Authorization: Bearer <任务A的令牌>
Content-Type: application/json

{}
```

返回样例见 `contracts/examples/bootstrap.json`。新会话用相同任务身份读取最新快照；不能让客户端自行拼接旧聊天记录作为正式状态。

```json
{
  "expected_version": 1,
  "summary": "已经完成参数校验",
  "next_steps": "根据最新接口契约补充调用与测试"
}
```

这是 `update_my_context` 的参数；版本取 `context.version`，不是 `task.version` 或 `project_version`。

### ContextUpdate 与 TaskPatch 的更新语义

`ContextUpdate`（`update_my_context`）对八个上下文文本字段采用以下规则：

| 输入 | 行为 |
| --- | --- |
| 省略某字段 | 保持该字段原值 |
| 显式 `null` | 忽略该字段，不清空 |
| 空字符串 `""` | 清空该字段 |
| 非 null 值与原值相同 | 仍是一次有效更新 |

结构校验通过后，服务端先检查版本：版本不匹配返回 409 `version_conflict`，不写数据或历史。版本匹配但没有任何非 null 更新字段（仅有 `expected_version`，或其他字段全是 null），返回 422 `invalid_input`，版本不增加。

版本匹配且存在非 null 更新字段时，版本恰好增加 1，同时保存一条完整历史快照，即使内容与原值相同。当前数据、版本和历史快照必须在同一事务中提交，失败全部回滚。

真正的空请求 `{}` 缺少必填 `expected_version`，返回 422 `invalid_input`；不可把它当成“读取”或成功的空操作。输入类沿用 `str_strip_whitespace=True`，因此纯空白文本也会归一化为空字符串。

`TaskPatch`（任务规划修改）不同：省略字段表示保持原值，`parent_id=null` 表示移除父任务；其他字段显式 null 均为非法参数。不要把 `TaskPatch` 的规则套用到 `ContextUpdate`。

## 示例：接口变更

`propose_change` 的参数：

```json
{
  "task_id": "task_api",
  "title": "报名接口增加学号",
  "rationale": "需要按学号限制重复报名",
  "expected_project_version": 3,
  "patch": {"contract": "POST /registrations: {name, student_id}; student_id 必填且唯一"}
}
```

管理员 `review_change`：`{"change_id":"chg_example","approve":true,"note":"确认采用 student_id 命名"}`。

受影响任务随后用自己的令牌调用 `acknowledge_change`，先提交 `status="acknowledged"`，修改完成后再提交 `status="completed"`，两次都需要 `note`。通知 ID 与决策版本固定，不允许对旧通知的确认覆盖新的通知。

## 统一错误

```json
{
  "error": {
    "code": "version_conflict",
    "message": "内容已更新，请重新读取后再提交",
    "details": []
  }
}
```

| HTTP | code 示例 | 客户端处理 |
| --- | --- | --- |
| 401 | `unauthorized` | 提示令牌缺失、失效或撤销，不回显令牌 |
| 403 | `forbidden` | 身份有效但无权操作；不改成管理员身份重试 |
| 404 | `task_not_found`、`notification_not_found`、`unknown_tool` | 对象不存在/不可见，或功能尚未实现 |
| 409 | `version_conflict`、`already_reviewed`、`invalid_transition`、`outstanding_changes` | 重新读取，向使用者解释冲突 |
| 422 | `invalid_input`、`dependency_cycle`、`parent_cycle` | 展示字段或结构问题；不得部分写入 |
| 500 | `internal_error` | 服务端记录详细原因，客户端只获取脱敏提示 |

统一类型为 `ErrorResponse` → `ErrorBody`。`details` 可省略；出现时是 `ErrorDetail[]`，每项只有字符串 `field` 和 `message`，与当前服务实际输出一致，例如：

```json
{"error":{"code":"invalid_input","message":"输入参数不合法","details":[{"field":"expected_version","message":"Field required"}]}}
```

`field` 是用点连接的参数路径；请求体解析错误可能使用 `body` 前缀。没有细节时服务端省略 `details`，不输出 null。类型中的默认 None 表示可缺省，使用 Pydantic 输出时应采用 `model_dump(exclude_none=True)`。所有失败路径都不得在响应、日志或页面中泄露令牌及其他任务的私有数据。

## B 的 MCP 接入约定

先暴露任务端 P0 工具，名称与 action 相同；输入 schema 从共享请求类生成，HTTP 转发时保持字段一致。不要把管理员审批工具暴露在普通任务的工具列表中。

配置仅作为后续示意，实际入口文件由 B 实现后填写：

```toml
[mcp_servers.relay]
command = 'D:\Projects\hackerson\.venv\Scripts\python.exe'
args = ['D:\Projects\hackerson\mcp_bridge\server.py']
env_vars = ['RELAY_TASK_TOKEN']

[mcp_servers.relay.env]
RELAY_API_URL = 'http://127.0.0.1:8765'
```

每位成员使用自己电脑的绝对路径和自己任务的令牌；不要把本例尚不存在的 `server.py` 当作已可运行配置。本轮不改用户全局 Codex 设置。

STDIO 配置字段依据 [OpenAI 官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。SDK 锁定 1.x，参考 [官方 Python SDK v1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)，避免混用 2.x 导入路径。

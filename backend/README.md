# 后端：可联调的 P0 服务

已按共享 v0.1 契约实现任务管理、令牌鉴权、上下文持久化与恢复、公开接口查询、消息、变更提案/人工审批、影响通知与处理状态。共享请求/响应字段与数据库结构没有改动。

## 启动

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m backend
```

默认地址 `http://127.0.0.1:8765`。`GET /health` 返回健康信息。
数据库位于 `data/relay.db`；首次启动生成管理员令牌，保存在 `.local/admin-token.txt`。
重启复用数据库和令牌。也可通过 `RELAY_ADMIN_TOKEN` 环境变量提供至少 24 字节的管理员令牌。

```powershell
# 仅在自己电脑查看管理员令牌；不要把它发给子任务或提交 Git。
Get-Content .local/admin-token.txt

# 指定其他数据库或端口：
.\.venv\Scripts\python.exe -m backend --port 8766 --db data/another.db
```

依赖仍位于根目录 `.venv/`，不需要全局安装新包。

## 联调入口

统一调用：`POST /api/tools/{action}`，请求体为 JSON 参数对象，带 `Authorization: Bearer <token>`。
`GET /api/tool-schemas` 返回当前实际实现操作的输入 schema。

已实现：

- 管理：`snapshot`、`edit_project`、`create_task`、`edit_task`、`delete_task`、`issue_task_token`。
- 任务：`list_tasks`、`get_task_status`、`get_my_context`、`update_my_context`、`report_status`。
- 通信：`query_module`、`send_message`、`get_messages`。
- 变更：`propose_change`、`list_changes`、`review_change`、`get_notifications`、`acknowledge_change`。
- 主角色访问：`issue_role_token`、`get_project_context`、`get_task_context`。

P1 的 `submit_change`、`get_review_feedback`、`review_submission`、`record_integration` 尚未实现，调用返回 404 `unknown_tool`。上下文和控制台响应中的 `submissions` 当前为空数组。没有模型自动规划、自动审核或 Git 合并。

## 给 MCP / 前端同学的最短流程

1. 获取后端分支代码或团队集成后的代码，安装依赖并启动服务。
2. 管理员调用 `create_task` 创建两个任务，先创建被依赖方。
3. 管理员分别调用 `issue_task_token`，将各自任务令牌交给对应执行者。再次签发会撤销该任务旧令牌。
4. 任务令牌调用 `get_my_context`；用 `context.version` 更新上下文，用 `task.version` 报告状态。
5. `query_module` 只返回已发布的 `contract`，不自动解答契约之外的问题。
6. 提案携带当前 `project_version`，审批由管理员执行。任务先确认理解通知，再报告完成修改。

PowerShell 创建任务与读取上下文的例子：

```powershell
$base = 'http://127.0.0.1:8765'
$adminHeaders = @{ Authorization = 'Bearer ' + (Get-Content .local/admin-token.txt -Raw).Trim() }
$body = @{ name = 'Sample task'; goal = 'Verify context recovery' } | ConvertTo-Json
$created = Invoke-RestMethod "$base/api/tools/create_task" -Method Post -Headers $adminHeaders -ContentType 'application/json' -Body $body
$body = @{ task_id = $created.task.task_id } | ConvertTo-Json
$issued = Invoke-RestMethod "$base/api/tools/issue_task_token" -Method Post -Headers $adminHeaders -ContentType 'application/json' -Body $body
$taskHeaders = @{ Authorization = 'Bearer ' + $issued.token }
Invoke-RestMethod "$base/api/tools/get_my_context" -Method Post -Headers $taskHeaders -ContentType 'application/json' -Body '{}'
```

MCP 适配器配置 `RELAY_API_URL=http://127.0.0.1:8765` 和该任务的 `RELAY_TASK_TOKEN`；适配器由 B 提供。
前端开发服务器将 `/api` 代理到后端；后台不默认开放跨域，本模块没有实现网页。

不同电脑上的 `127.0.0.1` 指向各自电脑。要共用一个后台，选择一台主机部署，通过可访问地址连接；需要时显式指定 `--host 0.0.0.0`，由团队配置防火墙及受保护的网络连接。本次没有开放公网端口。

## 版本、权限与数据处理

- 令牌仅保存哈希，任务身份由令牌确定；不能通过参数访问他人私有记录或签发凭据。
- 每个操作在同一 SQLite 事务内鉴权并读写，阻止旧版本并发覆盖；审批时任一步失败均回滚。
- 上下文保留历史快照，归档不删除历史，但撤销令牌、修复依赖/父子关系并通知受影响任务。
- 通知内容只含筛选后的变更摘要，不广播私有任务描述、全局内部内容或管理员内部理由。
- 管理员直接修改的理由保存在管理员消息记录中，仅管理员和主角色可查看。
- `ContextUpdate` 中省略或为 null 的字段不更新；清空文本请传空字符串。至少需要一个非 null 更新字段。
- `acknowledge_change` 对相同状态重试幂等；不能跳过确认，也不能回退状态。
- 未完成通知会阻止任务报告 `done`，但不会擅自改写任务当前状态。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=.tmp/backend-tests -p no:cacheprovider
.\.venv\Scripts\python.exe backend/tests/smoke_http.py
.\.venv\Scripts\python.exe scripts/check_contracts.py
```

第一条覆盖 API 权限隔离、输入错误、版本冲突、并发更新、持久化、图结构、审批回滚、通知状态、消息可见性和归档。
第二条启动真实 HTTP 子进程，跑通两个任务、上下文更新、跨模块查询、审批通知和后台重启恢复，结束后关闭子进程。
测试数据库和日志均位于 `.tmp/`，不写入正式 `data/relay.db`。
这些检查不能代替 B 的真实 MCP 客户端验证或 C 的页面联调。

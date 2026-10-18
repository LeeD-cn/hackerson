# BE-02：MCP 首批 HTTP 联调

本批对接 `get_my_context`、`update_my_context`、`query_module` 和 `/health`。
现有业务入口未改名，SQLite 结构没有变更。不要求 MCP 队友合并整条后端分支。

## 共享契约同步

共享契约独立提交：`39f524271569f2fff1015f78eaba676d5fb630cc`。
仅包含 `contracts/responses.py`、`docs/API_CONTRACT.md`、`scripts/check_contracts.py`。

由管理会话协调，在需要共享类型的分支、工作区干净时可只取这一笔：

```powershell
git fetch origin
git cherry-pick 39f524271569f2fff1015f78eaba676d5fb630cc
```

新增 `QueryModuleResponse`、`ErrorDetail`、`ErrorBody`、`ErrorResponse`，未改请求字段。
`error.details` 出现时是 `[{"field":"字段路径","message":"原因"}]`，没有细节时省略。

## 本地启动及建立数据

以下命令由持有后端代码的人在仓库根目录执行。这里使用 8770 端口和独立的测试数据库，避免与默认服务混淆。

窗口一：

```powershell
.\.venv\Scripts\python.exe -m backend --port 8770 --db data/be02.db
```

服务地址为 `http://127.0.0.1:8770`；先在浏览器访问 `/health`，应得到 `{"status":"ok","version":"0.1.0"}`。
默认管理员令牌在 `.local/admin-token.txt`，或由 `RELAY_ADMIN_TOKEN` 环境变量提供。种子工具使用同样的凭据来源。

窗口二：

```powershell
.\.venv\Scripts\python.exe -m backend.be02 seed --url http://127.0.0.1:8770
.\.venv\Scripts\python.exe -m backend.be02 check
```

`seed` 通过真实 HTTP 接口创建 B、A 两个任务，A 依赖 B；各有自己的令牌、公开接口、可区分的私有摘要。它会额外保留一个已被轮换撤销的 A 令牌，专门复现 401。

凭据保存在 **Git 忽略**的 `.local/be02/credentials.json`，不会打印到终端，也不进入文档或提交。
文件已存在时 `seed` 拒绝覆盖，不删除任务、不轮换已有联调身份；要重建一套数据，请使用新文件名：

```powershell
.\.venv\Scripts\python.exe -m backend.be02 seed --url http://127.0.0.1:8770 --credentials .local/be02/another.json
.\.venv\Scripts\python.exe -m backend.be02 check --credentials .local/be02/another.json
```

`check` 会真实修改这套测试数据的 A 上下文并增加版本，B 保持不变。成功后将最新上下文检查点保存到凭据文件，同时生成脱敏请求/响应报告 `credentials-report.json`。报告含身份别名和请求/响应体，不含真实令牌或 Authorization 头。报告仍保存在本地忽略目录。

凭据文件结构（这里只展示字段名，不提供真实凭据）：

```text
base_url
initialized
tasks.a.task_id / tasks.a.token / tasks.a.private_marker / tasks.a.expected_context
tasks.b.task_id / tasks.b.token / tasks.b.private_marker / tasks.b.expected_context
revoked_a_token
```

给 MCP 进程配置对应任务的 `RELAY_TASK_TOKEN` 和 `RELAY_API_URL`；不要把整个凭据文件交给单个任务，因为其中同时包含 A、B 的令牌。

## 三个接口的请求/响应

统一路径：`POST /api/tools/{action}`，JSON 请求体，`Authorization: Bearer <对应任务令牌>`。

1. `get_my_context`

请求：`{}`。输出为 `BootstrapContext`，包括本人 `task`、本人 `context`、必要依赖公开契约、相关通知等。结构示例见 `contracts/examples/bootstrap.json`，真实完整响应可在本地 `credentials-report.json` 中查看。

响应关键字段示意（非完整响应）：

```json
{"task":{"task_id":"<A的ID>"},"context":{"task_id":"<A的ID>","version":2,"data":{"summary":"<A的私有摘要>"}},"dependency_contracts":[{"task_id":"<B的ID>","name":"<B的名称>","contract":"<B的公开接口>","version":1}]}
```

2. `update_my_context`

请求中的 `expected_version` 必须取刚读取的 `context.version`，不要使用任务或项目版本：

```json
{"expected_version":2,"summary":null,"todos":"","next_steps":"继续实现调用"}
```

响应为完整 `TaskContext`：

```json
{"task_id":"<A的ID>","version":3,"data":{"summary":"<原摘要保持不变>","completed":"","todos":"","blockers":"","decisions":"","failed_attempts":"","next_steps":"继续实现调用","git_notes":""},"updated_at":"<UTC时间>"}
```

省略或 null 字段忽略，空字符串清空；同值更新也增加一次版本并写历史。仅有版本或全 null 时返回 422。旧版本返回 409，数据和历史不改变。完整规则见 `API_CONTRACT.md`；`TaskPatch` 的 null 规则与此不同。

3. `query_module`

请求：

```json
{"task_id":"<B的ID>","question":"请提供已发布接口"}
```

响应 `QueryModuleResponse`：

```json
{"contract":{"task_id":"<B的ID>","name":"<B的名称>","contract":"PUBLIC_B: GET /be02/b returns {\"ok\":true}","version":1},"query_id":"<消息ID>","mode":"published_contract","notice":"仅返回已发布接口；超出契约的问题由协调者通过消息回复。"}
```

不会返回 B 的私有上下文，也不会伪称模型回答了契约以外的问题。

## 复现错误

`check` 自动执行并把以下请求及实际响应记录到报告，也可以用 MCP 或 HTTP 客户端单独复现：

| 场景 | 操作 | 预期 |
| --- | --- | --- |
| 已失效令牌 | 用本地 `revoked_a_token` 调用 `get_my_context` | 401 `unauthorized` |
| 旧版本写入 | 读取版本 v，更新成功后再次携带 v 写入 | 409 `version_conflict`，当前值不改变 |
| 无更新字段 | `update_my_context` 只带当前 `expected_version` | 422 `invalid_input`，不增加版本 |
| 全 null | 当前版本加 `summary:null` | 422 `invalid_input`，不增加版本 |
| 空请求 | `update_my_context` 传 `{}` | 422 `invalid_input`，缺少版本 |
| 目标不存在 | `query_module` 的 `task_id` 为 `be02_missing_task` | 404 `task_not_found` |
| 越权私有上下文 | A 调用 `get_task_context` 指定 B | 403 `forbidden` |
| 未实现工具 | 调用 `be02_unimplemented_action` | 404 `unknown_tool` |

## 重启恢复验证

先执行 `check` 保存检查点。在窗口一 Ctrl+C 关闭后台，再用完全相同的数据库参数和管理员配置启动；窗口二执行：

```powershell
.\.venv\Scripts\python.exe -m backend.be02 verify-restored
```

应显示 `Both task contexts match the saved checkpoint.`。在检查点和验证之间不要让其他会话修改这套测试任务，否则检查点比较会失败。

也可以一次运行独立的真实 HTTP 测试，脚本自动启动、初始化、检查、重启并恢复：

```powershell
.\.venv\Scripts\python.exe -m backend.tests.smoke_be02
```

其数据库、管理员令牌、任务凭据、脱敏报告及日志保存在打印出的 `.local/be02/run-*` 内；测试结束会停止自己的服务进程。它不启动持久在线服务，也不修改 `data/be02.db`。

## 联调边界

当前交付为本地 HTTP 能力，尚未部署跨电脑共享服务。另一台电脑的 `127.0.0.1` 不指向你的后台；跨电脑地址、监听、防火墙和受保护传输仍需管理会话协调。
MCP 可先用本地后台验证三个工具；是否真正通过 MCP 调用成功，由 MCP 队友回报。本批没有扩展审核、自动合并或模型编排。

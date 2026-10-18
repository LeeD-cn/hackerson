# MCP-01 / MCP-02 联调交付报告

日期：2026-10-18。本文合并 MCP 实现交付、真实后端联调与 Git 同步结果，供管理会话评审并安排下一步任务。

**结论：MCP-01 已实现并推送；MCP-02 的官方 MCP SDK stdio 客户端连接真实后端验证已通过。实际 AI 调用和前端展示仍待验收，MCP-02 属于阶段交付。**

## 1. 分支、提交与同步

- 仓库：https://github.com/LeeD-cn/hackerson.git
- 分支：feature/mcp-bridge；未合入 main。
- 实现提交：c1c4f4c417d43e63930cc507c09b9d60d01617b0，feat: add task MCP stdio bridge。
- 实现已推送至 origin/feature/mcp-bridge。最近一次同步返回 Everything up-to-date，远端 SHA 与本地一致；新增本报告前工作区干净，没有遗漏的非忽略文件。
- MCP-02 未发现必须修改适配器的问题，没有新增业务代码或修改共享契约。本报告作为单独文档提交，报告提交 SHA 见本次交付消息和 Git 记录。
- 令牌、虚拟环境、数据库、运行日志和缓存不提交；本报告不包含真实令牌。

## 2. 文件与实现范围

| 文件 | 用途 |
| --- | --- |
| mcp_bridge/__init__.py | Python 模块标识 |
| mcp_bridge/server.py | 官方 Python MCP SDK 1.x stdio 适配器 |
| mcp_bridge/http_client.py | 环境配置、HTTP 转发、错误处理及令牌脱敏 |
| mcp_bridge/tests/test_http_client.py | HTTP 客户端单元测试 |
| mcp_bridge/tests/test_stdio.py | 官方 SDK stdio 客户端连接模拟 HTTP 服务的测试 |
| mcp_bridge/README.md | 启动与 Codex 配置说明 |
| mcp_bridge/DELIVERY_MCP01_MCP02.md | 本合并交付报告 |

仅暴露 get_my_context、update_my_context、query_module，输入复用共享请求类型。通过 HTTP 调用后端，不直接访问 SQLite。身份只来自 RELAY_TASK_TOKEN；query_module.task_id 仅为查询目标。权限、上下文版本及业务语义由后端判断。

适配器处理鉴权错误、版本冲突、连接失败与超时，不自动重试写请求；诊断写入 stderr，stdout 用于 MCP。未扩展消息、审批、通知工具，未实现管理员审批。

## 3. 本机环境与启动

- MCP 目录：D:\20261018EE黑客松\hackerson-mcp-bridge
- 独立后端工作树：D:\20261018EE黑客松\hackerson-be02
- 后端提交：6fd94f1e72c1700b46462725045807d839215585
- 后端地址：http://127.0.0.1:8770
- 数据库：后端工作树下的 data/be02.db，不将数据库路径传给 MCP。

从独立后端目录启动：

~~~powershell
.\.venv\Scripts\python.exe -m backend --port 8770 --db data/be02.db
~~~

MCP 直接启动示例，令牌仅在本机进程环境中赋值，不输出：

~~~powershell
cd 'D:\20261018EE黑客松\hackerson-mcp-bridge'
$env:RELAY_API_URL = 'http://127.0.0.1:8770'
$credentials = Get-Content 'D:\20261018EE黑客松\hackerson-be02\.local\be02\credentials.json' -Raw | ConvertFrom-Json
$env:RELAY_TASK_TOKEN = $credentials.tasks.a.token
Remove-Variable credentials
.\.venv\Scripts\python.exe -B .\mcp_bridge\server.py
~~~

必填变量为 RELAY_API_URL、RELAY_TASK_TOKEN；可选 RELAY_HTTP_TIMEOUT_SECONDS 默认 10 秒。任务 A 令牌取自本地 credentials.json 的 tasks.a.token，查询目标取 tasks.b.task_id。不要向单个任务模型提供含全部任务令牌的凭据文件。

Codex stdio 配置示例（客户端启动前需设置其可继承的任务令牌）：

~~~toml
[mcp_servers.relay]
command = 'D:\20261018EE黑客松\hackerson-mcp-bridge\.venv\Scripts\python.exe'
args = ['-B', 'D:\20261018EE黑客松\hackerson-mcp-bridge\mcp_bridge\server.py']
env_vars = ['RELAY_TASK_TOKEN']

[mcp_servers.relay.env]
RELAY_API_URL = 'http://127.0.0.1:8770'
~~~

上述是连接配置，不代表实际 AI 调用已通过。本次 CLI 使用临时配置，没有提交令牌配置或修改全局审批策略。服务曾保留供后续联调；阅读报告时是否仍在运行需届时确认。

## 4. 已执行的验证

以下是此前执行结果。本次仅整理报告和同步 Git，不重新运行测试。

### 4.1 契约检查、依赖检查及模拟验证

在 MCP 目录执行：

~~~powershell
.\.venv\Scripts\python.exe -B scripts/check_contracts.py
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -B -m pytest mcp_bridge/tests -q --basetemp=.tmp/pytest-final -o cache_dir=.cache/pytest-final
~~~

- 契约检查：11 张 schema 表、样例和约束检查通过，不表示所有运行时业务已实现。
- 依赖检查：No broken requirements found。
- 测试：52 passed in 12.79s，包括单元测试和真实 SDK stdio 客户端连接模拟 HTTP 服务的测试。
- 此组不是连接真实后端或实际 AI 模型的证明。

### 4.2 真实后端 HTTP 检查

在上述后端工作树运行：

~~~powershell
.\.venv\Scripts\python.exe -m backend.be02 seed --url http://127.0.0.1:8770
.\.venv\Scripts\python.exe -m backend.be02 check
~~~

/health 返回 status=ok、version=0.1.0；seed、check 均通过。凭据位于后端的 .local/be02/credentials.json，HTTP 脱敏报告位于 .local/be02/credentials-report.json。该报告是后端 HTTP 检查证据，不是 MCP 或 AI 调用记录。种子已存在，不应盲目重跑 seed；check 会更新测试上下文并增加版本。

### 4.3 官方 MCP stdio 客户端连接真实后端

此前执行命令：

~~~powershell
.\.venv\Scripts\python.exe -B .\.tmp\mcp02_real_stdio.py
~~~

临时脚本使用官方 SDK 的 stdio_client、ClientSession 启动适配器，连接真实 8770 后端执行断言，退出码为 0：

| 验证项 | 结果 |
| --- | --- |
| 工具发现 | 恰好为三个已交付工具 |
| 读取任务 A | 返回令牌对应的 A，初始上下文版本 v4 |
| 更新后重新读取 | v4 → v5，读回进度与写入一致 |
| summary:null | 原摘要保持不变 |
| 旧版本 v4 写入 | version_conflict，版本和进度不变 |
| todos 传空字符串 | 成功清空，v5 → v6 |
| 仅 expected_version 或更新字段全 null | invalid_input，版本保持 v6 |
| 查询 B | mode=published_contract，未包含私有上下文标记 |
| B 公开契约 | PUBLIC_B: GET /be02/b returns {"ok":true} |
| 已撤销的 A 令牌 | unauthorized，未回显令牌 |

v6 是当时最终版本，后续操作可能改变它。进度由 SDK 脚本保存，**不是实际 AI 模型写入**；即使测试进度字符串包含 AI client 字样，也不能当作 AI 调用证据。

用户随后要求停止验证，临时脚本已清理，仓库没有该脚本或完整 MCP-02 原始调用日志。此处依据当次输出记录结果，不将其描述为已提交的可重复执行验收脚本。

## 5. 待验收项及阻塞

### 实际 AI 客户端：未完成

Codex CLI 已加载 relay 服务并尝试 get_my_context。首次因 approval_policy=never 拒绝 MCP 调用；后续自动审批审查模型 gpt-5.6-luna 返回 404 不受支持，审查未完成、工具未执行。未成功完成 AI 的“读取 → 保存进度 → 重读 → 查询 B”链路，未绕过审批。

阻塞位于本机客户端审批审查模型的可用性，不是已证实的后端鉴权或 MCP 转发故障。临时复制的登录态文件、配置、事件日志和验证脚本已删除；临时状态目录递归清理曾被审查故障阻止，未宣称目录已全部清空。

### 前端展示：未完成

独立前端工作树：D:\20261018EE黑客松\hackerson-web-console，提交 fb6229e4073431bb99a04473251826aceb2d3db5。当前终端找不到 npm，未启动页面，也没有刷新后显示 AI 进度的证据。前端已有联调记录不能替代本次验收。

用户已要求停止进一步验证，后续由用户操作、我提供指导。页面应配置 RELAY_API_URL=http://127.0.0.1:8770，使用相同后端及数据库；控制台登录使用本地管理员令牌，不能使用 A 任务令牌。不同电脑的 127.0.0.1 不指向同一个服务。

## 6. 请管理会话安排下一步

1. 评审并接收已推送的 MCP-01 实现与本报告；MCP-02 按阶段交付记录。
2. 修复实际 Codex 客户端审批审查模型可用性后，指导用户完成 AI 调用链，记录调用顺序、更新前后版本及公开契约，不暴露令牌。
3. 准备 Node.js 22.12+ 和 npm，前端连接 8770 后端；刷新 A 的工作上下文，核对 AI 保存的同一条进度和版本。
4. 请明确优先补齐上述两个验收项还是安排下一批开发；当前仍只维护三个工具，不自行扩展功能或共享字段。

| 交付层次 | 状态 |
| --- | --- |
| MCP-01 实现、测试、说明及远端推送 | 完成 |
| 契约、依赖检查和模拟测试 | 此前通过 |
| 真实后端 seed/check | 此前通过 |
| 官方 MCP SDK stdio 客户端连接真实后端 | 此前通过 |
| 实际 AI 编程客户端成功调用链 | 待验收，审批审查模型不可用 |
| 页面显示 AI 保存的进度 | 待验收，页面未运行、尚无 AI 写入 |
| MCP-02 整体验收 | 阶段交付，保留上述两项 |

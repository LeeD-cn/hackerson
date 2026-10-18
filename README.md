# Relay：多人 AI Coding 协作框架

当前交付：任务控制台、后端权限与上下文、网页 AI 规划和三个 MCP 工具。跨电脑 Codex 读取/更新与网页展示已由用户验收。
用户已确认 AI 草案创建任务后，刷新仍保留任务及“下一步”中的交接提示词。核心演示链路已通过人工验收，模型服务仍有超时记录。详见 [交付报告](docs/DELIVERY.md)。

后端启动、接口可用范围与验证步骤见 [backend/README.md](backend/README.md)。

稳定身份属于任务，Codex 等工具是可替换的执行者。任务状态、权限和工作上下文由共享后端保存；代码状态以 Git 为准。
网页规划模型辅助生成分工和交接提示词，不改变各成员的编程模型，不会自动启动开发 AI。

## 快速启动

需要 Git、Python（项目环境为 3.13）和 Node.js（前端要求 22.12+ 的兼容版本）。新电脑在 PowerShell 执行：

```powershell
git clone https://github.com/LeeD-cn/hackerson.git
cd hackerson
.\scripts\setup.ps1
cd frontend
npm ci --no-audit --no-fund
cd ..
```

首次配置：创建 `.local/planning/`，将 `backend/planning.example.json` 复制为 `.local/planning/settings.json`，
在本地 `.local/planning/api-key.txt` 填写模型 API 密钥。不要覆盖已有配置或提交密钥。
模板地址为 `https://llmapi.paratera.com`，模型为 `DeepSeek-V4-Pro-0813`，等待上限 180 秒。

终端一启动后端：

```powershell
.\scripts\start_planner.ps1
```

默认服务 `http://127.0.0.1:8765`，数据库 `data/relay.db`。
管理员令牌在 `.local/admin-token.txt`，或由 `RELAY_ADMIN_TOKEN` 指定。模型密钥与管理员令牌不同。
不使用网页 AI 时，可执行 `.\.venv\Scripts\python.exe -m backend` 启动基础任务服务，未配置的规划接口明确报错。

终端二在同一仓库根目录启动前端：

```powershell
.\scripts\start_frontend.ps1
```

打开 **http://127.0.0.1:5173**，使用对应后端的管理员令牌登录。“AI 任务规划”支持讨论需求、编辑草案和确认创建。
其他端口可用 `start_planner.ps1 -Port 8780 -Database data/demo.db`，配合 `start_frontend.ps1 -BackendUrl http://127.0.0.1:8780 -Port 5175`。
两条命令在不同终端执行；前后端要连接同一个服务和数据库。新克隆目录不自动拥有原来的任务或令牌。

## 队友电脑接入 MCP

主机后端可用 `start_planner.ps1 -BindAddress <主机的Wi-Fi IPv4> -Port 8765` 监听明确的网卡地址，
主机前端代理也使用该地址。先让队友浏览器访问 `http://<主机IPv4>:8765/health`。
然后管理员通过 issue_task_token 签发任务令牌，私下交给对应成员。

成员 Codex 配置本地 stdio 服务：命令为本机项目 `.venv/Scripts/python.exe` 的绝对路径，参数为 `-B` 和本机 `mcp_bridge/server.py` 的绝对路径；
环境变量 RELAY_API_URL 指向后端主机，RELAY_TASK_TOKEN 使用任务令牌。不要使用管理员令牌或模型 API 密钥。

现有工具：get_my_context、update_my_context、query_module。正式状态、消息和通知更新尚未暴露为 MCP 工具。
读取任务、按最新 context.version 保存工作记录，网页刷新后查看结果。具体步骤见 [演示手册](docs/DEMO.md) 和 [MCP README](mcp_bridge/README.md)。

## 三人分工

| 成员 | 负责内容 | 工作分支 | 主要目录 |
| --- | --- | --- | --- |
| A（你） | 后端、数据库、权限、变更业务流程；协调接口与合并 | `feature/backend-core` | `backend/`、`contracts/` |
| B | MCP 工具、Codex 接入、双身份与上下文恢复验证 | `feature/mcp-bridge` | `mcp_bridge/` |
| C | 控制台、任务依赖展示、审批与通知页面、页面联调 | `feature/web-console` | `frontend/` |

B、C 的具体人员由团队安排。以上是开发分工，不限制产品内任务类型；产品任务必须允许自由命名和拆分。

## 先阅读

- [交付范围、证据和未完成事项](docs/DELIVERY.md)
- [演示与人工验收](docs/DEMO.md)
- [网页 AI 规划接口](docs/AI_PLANNING.md)
- [MCP 队友交付报告](mcp_bridge/DELIVERY_MCP01_MCP02.md)

1. [三人分工与交付顺序](docs/TEAM.md)
2. [Git 协作流程](docs/GIT_WORKFLOW.md)
3. [数据结构与权限边界](docs/DATA_MODEL.md)
4. [HTTP / MCP 共享接口契约](docs/API_CONTRACT.md)
5. [给三位开发者的开工说明](docs/HANDOFF.md)
6. [原始产品需求](docs/PRODUCT_BRIEF.md)

`contracts/schema.sql` 是 SQLite 初始结构；`contracts/requests.py`、`contracts/responses.py` 是共享输入输出类型。契约版本为 **v0.1**，修改时同步通知受影响成员，不要各自另起一套字段。

## 本地环境（依赖留在项目目录）

当前使用 Python 3.13 + FastAPI + SQLite + 官方 MCP Python SDK 1.x，前端使用 React + TypeScript + Vite。

```powershell
# 在项目目录执行；只设置当前进程的缓存/临时目录。
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1

# 只检查数据结构和契约，不启动服务。
.\.venv\Scripts\python.exe scripts/check_contracts.py
```

`.venv/`、`.cache/`、`.tmp/`、`data/`、`.local/` 均位于当前项目内并被 Git 忽略。
依赖安装使用项目虚拟环境，不向全局 Python 或 C 盘安装项目包。
`requirements.txt` 表达兼容范围，`requirements.lock.txt` 固定本次实际环境版本。

## 初始协作基线（历史）

- 清理提前生成的未完成业务代码，保留干净的模块边界。
- 建立本地 Git、共享初始提交与三个工作分支。
- 建立 SQL 结构、输入输出契约、样例和检查脚本。
- 初始提交仅包含准备文件；后续后端实现状态见上方链接。
- 远程仓库为 `https://github.com/LeeD-cn/hackerson.git`，成员使用各自功能分支。

请勿把“契约检查通过”或“后端测试通过”理解为“整个产品已通过验收”。

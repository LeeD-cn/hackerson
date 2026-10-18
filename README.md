# 多人 AI Coding 协作框架

当前阶段：**三人协作准备基线，尚未实现可运行 MVP。**

稳定身份属于任务，Codex 等工具是可替换的执行者。任务状态、权限和工作上下文由共享后端保存；代码状态以 Git 为准。

## 三人分工

| 成员 | 负责内容 | 工作分支 | 主要目录 |
| --- | --- | --- | --- |
| A（你） | 后端、数据库、权限、变更业务流程；协调接口与合并 | `feature/backend-core` | `backend/`、`contracts/` |
| B | MCP 工具、Codex 接入、双身份与上下文恢复验证 | `feature/mcp-bridge` | `mcp_bridge/` |
| C | 控制台、任务依赖展示、审批与通知页面、页面联调 | `feature/web-console` | `frontend/` |

B、C 的具体人员由团队安排。以上是开发分工，不限制产品内任务类型；产品任务必须允许自由命名和拆分。

## 先阅读

1. [三人分工与交付顺序](docs/TEAM.md)
2. [Git 协作流程](docs/GIT_WORKFLOW.md)
3. [数据结构与权限边界](docs/DATA_MODEL.md)
4. [HTTP / MCP 共享接口契约](docs/API_CONTRACT.md)
5. [给三位开发者的开工说明](docs/HANDOFF.md)
6. [原始产品需求](docs/PRODUCT_BRIEF.md)

`contracts/schema.sql` 是 SQLite 初始结构；`contracts/requests.py`、`contracts/responses.py` 是共享输入输出类型。契约版本为 **v0.1**，修改时同步通知受影响成员，不要各自另起一套字段。

## 本地环境（依赖留在项目目录）

当前选择 Python 3.13 + FastAPI + SQLite + 官方 MCP Python SDK 1.x。前端框架由 C 开工时选择，推荐 React + TypeScript + Vite。

```powershell
# 在项目目录执行；只设置当前进程的缓存/临时目录。
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1

# 只检查数据结构和契约，不启动服务。
.\.venv\Scripts\python.exe scripts/check_contracts.py
```

`.venv/`、`.cache/`、`.tmp/`、`data/`、`.local/` 均位于当前项目内并被 Git 忽略。
依赖安装使用项目虚拟环境，不向全局 Python 或 C 盘安装项目包。
`requirements.txt` 表达兼容范围，`requirements.lock.txt` 固定本次实际环境版本。

## 本次准备范围

- 清理提前生成的未完成业务代码，保留干净的模块边界。
- 建立本地 Git、共享初始提交与三个工作分支。
- 建立 SQL 结构、输入输出契约、样例和检查脚本。
- 没有启动后台、创建业务数据库、实现 UI/MCP、调用模型、自动合并或发布网站。
- 远程仓库尚未建立，其他成员需在建立远程后克隆，具体见 Git 流程。

下一步由你们按分工开始实现。请勿把“契约检查通过”理解为“产品功能通过验收”。

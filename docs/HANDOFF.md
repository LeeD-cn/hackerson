# 给三个开发会话的开工说明

这是后续开工时使用的说明。本次只建立准备基线，不据此自动开始业务实现。

## A：后端（你）

> 在 `feature/backend-core` 分支工作。先读 README、docs/TEAM.md、docs/DATA_MODEL.md、docs/API_CONTRACT.md 及 contracts/。你负责 backend/。优先实现 SQLite、令牌鉴权、任务和上下文 HTTP 操作，让 B/C 尽早联调。MCP 客户端不直接操作数据库，任务身份从令牌解析。共享契约变更要通知另外两位。不要实现前端或 MCP 适配器。先交付能验证的 P0，不做自动调度或自动合并。

## B：MCP

> 在 `feature/mcp-bridge` 分支工作。先读 README、docs/TEAM.md、docs/API_CONTRACT.md 及 contracts/。你负责 mcp_bridge/。基于官方 Python MCP SDK 1.x，用 stdio 暴露任务工具，转发到同一个 HTTP 后台。服务地址和任务令牌通过环境变量注入，不访问 SQLite，不自行决定权限或变更生效。先交付上下文读取/更新、接口查询、通知处理，再补充其他工具。使用两个独立任务凭据验证隔离和新会话恢复。需要调整接口时先与 A 协调。

## C：控制台

> 在 `feature/web-console` 分支工作。先读 README、docs/TEAM.md、docs/API_CONTRACT.md 及 contracts/。你负责 frontend/。完成任务列表、依赖关系、创建/编辑、上下文摘要、提案审批和通知状态。前端框架可以选 React + TypeScript + Vite；业务规则以共享契约为准。后台未就绪时使用 contracts/examples/ 的样例并标记，联调时必须换成真实 API。不要在页面写死任务类型，不把令牌提交 Git，不把通知已发送显示为修改已完成。需要调整接口时先与 A 协调。

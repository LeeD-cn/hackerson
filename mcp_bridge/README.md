# B：MCP 与接入

本目录目前只有任务边界，没有 MCP 实现。

按 `../docs/API_CONTRACT.md` 的操作名与参数提供 MCP 工具。使用官方 Python MCP SDK。
MCP 作为轻量适配层，通过 HTTP 请求共享后端；不创建数据库、不直接读 SQLite。
进程环境提供 `RELAY_API_URL` 与任务令牌 `RELAY_TASK_TOKEN`。

独立成员可以各运行一个 stdio 适配进程，所有进程访问同一后端。
这与“只有一个远程 HTTP MCP 进程”不同；MVP 先采用前者，避免同时实现两套传输。

验收重点：真实工具发现与调用、两种任务身份隔离、重启会话后上下文恢复、HTTP 错误映射到 MCP 错误。

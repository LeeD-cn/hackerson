# A：后端与数据（你负责）

业务实现从这里开始。本目录目前没有服务代码。

先阅读 `../docs/TEAM.md`、`../docs/API_CONTRACT.md`、`../docs/DATA_MODEL.md`。
以 `../contracts/schema.sql` 和 `../contracts/requests.py` 为共同基线。

交付顺序：SQLite 初始化 → 令牌鉴权 → 任务与上下文 → 查询与消息 → 提案审批及通知。
先实现 `get_my_context`、`update_my_context`、`query_module`，尽早让 B、C 联调。
服务端独占数据库；所有角色和状态检查都由本模块执行。

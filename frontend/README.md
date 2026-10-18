# Relay 前端控制台

交付更新：已补管理员“AI 任务规划”页面，支持对话、草案人工编辑、确认创建和规划记录恢复。
统一启动见根目录 README，验收证据与边界见 [DELIVERY.md](../docs/DELIVERY.md)。
下面原有功能清单和 BE-02 记录保留为该阶段历史，不代表新增规划流程已完成全部人工验收。

基于 React + TypeScript + Vite，已接入真实后端 HTTP API。没有内置演示数据或 mock fallback。

对接基线：`origin/feature/backend-core` 的 `1ad51f2`（包含首批服务 `c24dbca`）。共享契约与后端代码未修改。

BE-02 追加同步：仅 cherry-pick 共享契约 `39f5242`（本分支对应 `20b3d7e`），未合入整条最新后端分支。已使用独立的干净后端 `6fd94f1` 完成真实页面联调。连接和刷新时先检查 `/health`，再读取管理快照。

## 本批功能

- 管理员令牌登录；协调者、审核者只读查看；任务令牌不能进入管理控制台。
- 任务列表、名称/目标/执行者搜索、状态筛选、任务详情。
- 创建和编辑任务：名称、目标、验收、描述、接口、约束、执行者、Git 分支、父任务、依赖。
- 查看当前工作上下文、前置/后续依赖、项目版本、任务版本。
- 查看真实变更通知并按待确认／已确认理解／已完成修改筛选。
- 处理加载、空列表、401、403、422、版本冲突、网络故障；写入不会自动重试。
- 编辑只提交发生变化的字段和 `expected_version`；409 保留草稿，用户可明确选择载入最新内容。

通知状态由任务执行者通过后端/MCP 更新。控制台不会把送达通知视为任务完成，也不会代替执行者报告进度。

本批未实现：归档任务的页面操作、项目设置、消息收发、提案审批、任务令牌签发页面、Git 审核页面；这些不是本次任务列表/详情/创建/编辑联调的验收项。

## 启动（普通克隆目录）

要求：已安装 Node.js 22.12+ 或兼容的较新版本，本次验证 Node.js 24.18.0。Python 依赖按仓库根 README 安装。

终端一，在仓库根目录启动后端：

```powershell
.\.venv\Scripts\python.exe -m backend
```

终端二，启动前端：

```powershell
cd frontend
npm ci --no-audit --no-fund
npm run dev
```

打开 `http://127.0.0.1:5173`。使用**本次启动后端所在仓库目录**的 `.local/admin-token.txt` 中的令牌登录。不要把令牌发到群里或提交 Git。

令牌可以只保存在内存，也可勾选在当前标签页的 `sessionStorage` 中记住以便刷新；退出登录会清除。不使用 `localStorage`，不硬编码、不放进 URL。

依赖安装到 `frontend/node_modules`。`frontend/.npmrc` 将 npm 缓存指向该克隆目录的 `.cache/npm`；不需要全局安装依赖。

## 独立 worktree / 端口冲突

本次在 `D:\Projects\hackerson\.worktrees\web-console` 开发，保留原目录后端会话的未提交修改。worktree 不会自动拥有原目录的 `.venv`，可以显式复用原环境：

```powershell
cd D:\Projects\hackerson\.worktrees\web-console
& 'D:\Projects\hackerson\.venv\Scripts\python.exe' -m backend --port 8766
```

另一个终端：

```powershell
cd D:\Projects\hackerson\.worktrees\web-console\frontend
$env:RELAY_API_URL = 'http://127.0.0.1:8766'
npm run dev
```

此时使用 **worktree 下** `.local/admin-token.txt` 的令牌，数据库也在 worktree 的 `data/` 内。
若 5173 已占用，可执行 `npm run dev -- --port 5174`；Vite 使用严格端口，不会悄悄切换地址。

`RELAY_API_URL` 是 Vite 进程使用的后台 origin，默认为 `http://127.0.0.1:8765`。前端始终同源请求 `/api/tools/{action}`，Vite 代理到后台；不需要修改后台 CORS。改变该变量后要重启 Vite。

多人共用后台时，把 `RELAY_API_URL` 改为后台主机的可达地址。后台监听、HTTPS 和网络访问策略由后端部署负责；不要把任何凭据放进 `VITE_*` 环境变量。

## 构建与验证

```powershell
cd frontend
npm run build
npm run test:e2e
```

端到端脚本默认使用根目录 `.venv`，Windows 默认使用已安装的 Chrome，不自动下载浏览器。可以指定环境：

```powershell
$env:RELAY_PYTHON = 'D:\Projects\hackerson\.venv\Scripts\python.exe'
$env:RELAY_BROWSER_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
npm run test:e2e
```

其他平台可设置 `RELAY_BROWSER_PATH` 指向已安装的 Chromium 系浏览器，或安装 Playwright 的 Chromium 后运行。

脚本启动隔离的真实后端、Vite 与无头浏览器，使用临时端口、随机令牌和 `frontend/.tmp/` 内的数据库；不连接你正在运行的服务，不写正式数据库。结束或中断后关闭所创建的进程。截图保存在 `frontend/artifacts/`，日志在 `frontend/.tmp/e2e-*/`，均不提交。

`npm run build` 输出 `frontend/dist`。本地可执行 `npm run preview` 在 4173 预览，仍通过 Vite 代理连接后台。实际部署静态产物时，托管服务器需要另外配置 `/api` 反向代理；单独上传 dist 不会自动提供后台连接。

具体实测结果见 [INTEGRATION.md](INTEGRATION.md)。

## BE-02 本地接入与人工验收

最新后端从**包含 `6fd94f1` 的干净目录**单独启动。不要为了运行 BE-02 把整条后端分支合入前端，也不要使用未提交的 P1 草稿。

本机已准备的隔离后端目录为 `D:\Projects\hackerson\.worktrees\be02-frontend`。终端一：

```powershell
cd D:\Projects\hackerson\.worktrees\be02-frontend
& 'D:\Projects\hackerson\.venv\Scripts\python.exe' -m backend --port 8770 --db data/be02.db
```

终端二：

```powershell
cd D:\Projects\hackerson\.worktrees\web-console\frontend
$env:RELAY_API_URL = 'http://127.0.0.1:8770'
npm run dev
```

在 `http://127.0.0.1:5173` 使用**隔离后端目录下**的 `.local/admin-token.txt` 登录。此文件不要与前端所在目录或其他后台的令牌文件混用。

按需在后端目录运行 `python -m backend.be02 seed --url http://127.0.0.1:8770` 和 `python -m backend.be02 check`，其中 `python` 应替换为上面的虚拟环境解释器。完整说明见后端分支的 `docs/BE02_INTEGRATION.md`。不要将 `.local/be02/credentials.json` 复制到前端源码。

人工验收建议：

1. 登录后核对项目及已有任务是否正确。
2. 创建一个有实际名称、目标、验收标准的任务，确认详情显示完整。
3. 编辑目标、执行者和依赖，保存后刷新浏览器，确认数据仍在。
4. 设置父任务，再改回无父任务，确认原有目标和依赖没有被清空。
5. 查看上下文与变更通知，确认文案易懂，且“已确认理解”没有被当成任务完成。
6. 调整窗口宽度，检查排版、字号、表单填写是否顺手；将不满意之处反馈给前端会话。

核心自动检查已经执行，无需人工重复所有错误分支。自动检查的服务会在结束后关闭，以上命令用于你实际打开页面验收。

需要复现 BE-02 自动联调时，在前端目录指定后台代码来源（不需要合并后台分支）：

```powershell
$env:RELAY_PYTHON = 'D:\Projects\hackerson\.venv\Scripts\python.exe'
$env:RELAY_BACKEND_ROOT = 'D:\Projects\hackerson\.worktrees\be02-frontend'
$env:RELAY_BE02 = '1'
npm run test:e2e
```

该模式会在隔离测试服务上调用 BE-02 seed/check，检查页面上下文展示及重启恢复；测试凭据留在后台目录的 `.local/be02/frontend-*.json`，不会进入源码。

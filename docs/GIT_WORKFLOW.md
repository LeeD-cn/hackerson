# Git 协作流程

## 当前基线

本地建立 `main`，准备文件作为初始提交。三个功能分支从同一个提交分出：

- `feature/backend-core`：A（你）
- `feature/mcp-bridge`：B
- `feature/web-console`：C

当前电脑切换到 A 的分支。三人各用自己的克隆目录，不要在同一目录同时切换分支。

## 创建远程后

在 GitHub 或 Gitee 建立**空仓库**，先不要勾选自动生成 README、许可证或 gitignore。仓库可见性和平台由团队选择；本次没有代建远程仓库或推送。

A 将下面的地址替换为真实地址后执行：

```powershell
git remote add origin <远程仓库地址>
git push -u origin main
git push -u origin feature/backend-core
git push origin feature/mcp-bridge feature/web-console
```

邀请另外两位成员加入仓库。B 和 C 在各自电脑执行：

```powershell
git clone <远程仓库地址> hackerson
cd hackerson
# B 使用这一条；C 把分支名改成 feature/web-console。
git switch --track origin/feature/mcp-bridge
```

如平台支持，给 `main` 设置保护规则：通过 PR 合并，至少另一位成员看过，禁止强制推送。**创建本地分支不等于已配置远程保护规则。**

## 每轮开发

```powershell
git status
git fetch origin
# 在自己的功能分支，且工作区干净时同步。
git merge origin/main

# 修改自己的目录，完成本模块检查后，只添加预期文件。
git add <本次修改的文件>
git commit -m "feat: describe the completed change"
git push
```

不要把未完成更改藏进共享主分支，不要使用 force push 改写队友可能已拉取的提交。

## 合并

通过 PR 将功能分支合入 `main`，在 PR 描述中写明：行为变化、验证结果、接口是否改变、未完成事项。合并前确认共享契约和其他两端兼容。

初次集成顺序建议：后端最小 API → MCP 接入 → 控制台；后续持续小批量合并，避免最后一次性整合。

## 不提交的文件

虚拟环境、依赖缓存、临时目录、数据库及 WAL 文件、令牌、`.env`、日志、构建产物不进入 Git。
提交数据库**结构和迁移**，不提交运行中的 SQLite 文件。

共享代码仓库不应包含管理员令牌或私有任务数据库。应用权限只约束服务端访问，不能阻止拥有数据库文件读权限的人直接读取文件；实际协作时数据库和管理员凭据应仅保存在后台主机。

# 服务器运维入口

该目录用于从本地 E:\myfund11111 管理服务器。当前已具备只读巡检和本地代码检查入口；正式部署、数据库备份和回滚必须基于服务器实际环境执行，并保留明确的发布门禁。

## 配置

先复制无敏感信息模板：

```powershell
# 创建仅保存在本机的服务器配置文件；现有 .gitignore 会忽略该文件
Copy-Item -LiteralPath 'E:\myfund11111\ops\.env.example' -Destination 'E:\myfund11111\ops\.env'
```

然后编辑 `E:\myfund11111\ops\.env`，填写服务器地址、SSH 用户、端口和项目绝对路径。不要在其中保存 SSH 私钥正文、数据库密码或 API Key。

首次连接前，应在独立终端人工连接一次并核对 SSH 主机指纹。巡检脚本默认要求主机已经存在于 `known_hosts`，不会自动接受未知主机。

## 只读巡检

```powershell
# 检查 SSH、服务器基础状态和远程 Git 工作区，不读取数据库与 .env
& 'E:\myfund11111\ops\Test-ServerConnection.ps1'
```

巡检内容包括主机、系统时间、磁盘、Git 提交、工作区状态、Docker 和 systemd 基础状态。脚本不会重启服务、拉取代码、查询数据库或修改服务器文件。

## 本地开发检查

```powershell
# 首次初始化固定 Python、后端锁定依赖、本地配置和前端依赖。
& 'E:\myfund11111\ops\Initialize-LocalDevelopment.ps1'

# 只做 Python 语法、前端元数据、敏感文件和 Git 差异检查。
& 'E:\myfund11111\ops\Invoke-LocalChecks.ps1'

# 同时运行分析引擎、后端服务测试和前端构建。
& 'E:\myfund11111\ops\Invoke-LocalChecks.ps1' -RunPythonTests -BuildFrontend
```

本地检查只使用仓库源码和虚构测试夹具，不连接服务器数据库，也不会读取服务器配置。

本地合成 MySQL 的启动、迁移、停止和故障处理见 `E:\myfund11111\docs\development\LOCAL_DEVELOPMENT_ENVIRONMENT.md`。

## 当前服务器接入状态

- SSH 密钥已绑定并通过主机指纹校验。
- 服务器为 Rocky Linux；当前 my-funds 生产应用由 Compose project `my-funds-production-direct1` 承载。
- backend 使用 `my-funds-production-backend:30e8838-multiplatform`，frontend 使用 `my-funds-production-frontend:30e8838-multiplatform`；2026-09-23 复核确认各一个运行实例，后端健康接口、前端首页、确认份额 API 和多平台页面标记均通过。
- MySQL 为服务器主机进程，NewAPI 的 MySQL 容器不是 my-funds 业务数据库。
- 当前应用发布源为固定 Git 提交 `30e88380673deec82aa5dc7debe31de5714cd339`，旧生产工作区不得作为发布源或被覆盖式拉取。
- 服务器应用 `.env` 和 `$HOME/my-funds-production-releases/mf-multiplatform-30e8838/compose.yml.before` 权限均已收紧为仅属主可读写；离线发布归档保留供核验和回滚使用。
- OpenClaw 固定决策任务为工作日 14:00、`Asia/Shanghai`，负责交易日判断和邮件，不负责自动交易。

## 发布门禁

正式发布前必须同时满足：

1. 本地检查通过，目标提交已推送到 GitHub。
2. 服务器工作区干净，或所有线上热修已经审查并进入目标提交。
3. 服务器端数据库备份工具已确认可用，备份留在服务器，不下载到本地。
4. 发布后完成后端健康检查、前端首页检查和关键 API 检查。
5. OpenClaw 和其他执行端没有并发写入，自动任务与 systemd 重启策略已经记录暂停和恢复方式。

2026-09-19 的 DBSAFE2 记录已完成服务器内数据库备份和隔离恢复核对。该记录证明当时的备份可恢复，不替代未来 schema 或生产数据变更前的新备份。

Sol 与 Luna 的长期后台调度规则见 `E:\myfund11111\docs\operations\CODEX_LUNA_ORCHESTRATION.md`；Codex、Luna 与 OpenClaw 的任务认领、分支、热修回收和发布窗口规则见 `E:\myfund11111\docs\operations\OPENCLAW_CODEX_COLLABORATION.md`。

## 后续扩展

- 将已经验证的“固定 SHA、离线归档、固定镜像、Compose 切换和回滚”流程固化为可审查的部署脚本。
- 为每次数据库变更生成独立备份、隔离恢复和逐表计数证据。
- 记录每次生产镜像、OpenClaw 任务状态、健康检查和回滚目标。
- 将前端依赖审计和入口包拆分作为独立维护任务处理。

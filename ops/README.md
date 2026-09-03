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
- 服务器为 Rocky Linux + systemd。前端 unit 正常运行；backend unit 的失败自动重试已停止，旧健康 uvicorn 继续由 `tat_agent.service` 控制，后端健康接口与前端首页均已验证。
- MySQL 为服务器主机进程，NewAPI 的 MySQL 容器不是 my-funds 业务数据库。
- 服务器工作区原有 3 个未提交热修已经审查并进入 GitHub 提交 `5f8bc18`；生产目录仍保留这些差异，部署时禁止覆盖式拉取。
- 服务器应用 .env 权限已收紧为仅属主可读写。

## 发布门禁

正式发布前必须同时满足：

1. 本地检查通过，目标提交已推送到 GitHub。
2. 服务器工作区干净，或所有线上热修已经审查并进入目标提交。
3. 服务器端数据库备份工具已确认可用，备份留在服务器，不下载到本地。
4. 发布后完成后端健康检查、前端首页检查和关键 API 检查。
5. OpenClaw 和其他执行端没有并发写入，自动任务与 systemd 重启策略已经记录暂停和恢复方式。

当前服务器尚未发现可直接调用的 mysqldump 客户端，因此数据库备份自动化仍是发布前门禁，不能被跳过。

Sol 与 Luna 的长期后台调度规则见 `E:\myfund11111\docs\operations\CODEX_LUNA_ORCHESTRATION.md`；Codex、Luna 与 OpenClaw 的任务认领、分支、热修回收和发布窗口规则见 `E:\myfund11111\docs\operations\OPENCLAW_CODEX_COLLABORATION.md`。

## 后续扩展

- Deploy-Server.ps1：在热修合并、备份方式确认后部署指定 Git SHA。
- 服务器端数据库备份和恢复演练。
- systemd 服务清单与正式前端构建切换。
- 发布记录与回滚验证。

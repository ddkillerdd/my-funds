# Luna 生产后端稳定化与后续恢复执行令

> 编写日期：2026-09-03
> 本地仓库：`E:\myfund11111`
> 当前阶段：第一、第二阶段已经完成；失败的 systemd 自动重试已停止，旧健康后端继续服务，等待用户确认恢复 `04` 第二阶段
> 执行角色：Luna 负责最小漂移复核和经用户逐项确认的生产稳定化；本文件不自动授权任何服务器写操作

## 1. 目标与优先级

当前目标不是继续增加功能，而是按以下顺序恢复可控运行：

1. 阻止 `fund-advisor-backend.service` 每 10 秒产生一次失败重试。
2. 保留当前仍能通过 `/health` 的旧 uvicorn 进程，不制造业务中断。
3. 明确 OpenClaw、systemd 和旧 uvicorn 的控制边界，避免多个控制端互相拉起。
4. 生产临时稳定后，恢复 `04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md` 的本地发布包与隔离 staging 流程。
5. staging 验收通过、备份与回滚门禁满足后，再安排生产单实例切换。

本文件不授权功能开发、P1、策略参数调整、数据库操作、staging 部署或生产代码迁移。

## 2. 必须完整阅读

开始前按顺序完整阅读：

1. `E:\myfund11111\AGENTS.md`
2. `E:\myfund11111\00_LUNA_START_HERE.md`
3. `E:\myfund11111\LUNA_HANDOFF.md`
4. `E:\myfund11111\02_LUNA_SERVER_RELEASE_READINESS.md`
5. `E:\myfund11111\03_LUNA_OPENCLAW_COLLABORATION.md`
6. `E:\myfund11111\04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md`
7. `E:\myfund11111\05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md`
8. `E:\myfund11111\docs\operations\SYSTEM_ARCHITECTURE.md`
9. `E:\myfund11111\docs\operations\RUNBOOK.md`
10. `E:\myfund11111\docs\operations\CODEX_LUNA_ORCHESTRATION.md`
11. `E:\myfund11111\docs\operations\OPENCLAW_CODEX_COLLABORATION.md`
12. `E:\myfund11111\ops\README.md`
13. 本文件 `E:\myfund11111\06_LUNA_PRODUCTION_STABILIZATION.md`

若文档冲突，以 `AGENTS.md`、用户最新指令、本文件的逐阶段授权门和更严格的生产安全规则为准。

## 3. 2026-09-03 只读诊断基线

以下是交接快照，Luna 必须实时复核，不能视为永久事实。

### 3.1 本地与 GitHub

- 本地分支为 `codex/p0-server-readiness`。
- 本地、跟踪分支和 GitHub 分支均为完整 SHA `5f8bc18683c807dd0ef18b3b35735a7b4cffd016`。
- 暂存区为空。
- 当前工作区为 25 个已知 staging/文档候选文件加 5 个第四组文件；新增候选是本次长期 Sol/Luna 调度规范。
- 5 个第四组文件必须原样保留：
  - `fund-advisor/backend/services/calendar_service.py`
  - `fund-advisor/backend/services/excel_parser.py`
  - `fund-advisor/backend/services/nav_service.py`
  - `fund-analyzer/tests/test_position.py`
  - `fund-analyzer/tests/test_screener.py`

### 3.2 服务器生产代码

- 生产 Git 工作区为 `main` 的 `afc19e9b203141e8e604fc3f1b9f5dd438637a81`。
- 生产工作区只有 3 个已知未提交热修文件：
  - `fund-advisor/backend/services/advisor_service.py`
  - `fund-analyzer/engine/analyzer.py`
  - `fund-analyzer/engine/llm_client.py`
- systemd `WorkingDirectory` 已确认是生产 Git 工作区内的 `fund-advisor` 子目录，不是独立代码副本。
- systemd 使用的 uvicorn 虚拟环境路径位于另一套历史目录，和生产 Git 工作区不在同一棵发布目录中。
- 服务器生产代码没有 `backend/engine_bridge.py`；不启动应用的模块定位也无法解析 `backend.engine_bridge` 和 `engine.analyzer`。
- GitHub 的发布候选包含本地桥接实现，但尚未通过 `04` 的依赖锁、干净快照和 staging 验收门禁，禁止直接覆盖生产。

### 3.3 后端、前端与 OpenClaw

- `fund-advisor-backend.service` 配置仍为 `Restart=always`，但 Luna 已执行停止，unit 不再自动重试。
- 停止后观察 61 秒，累计重启计数稳定在 6716；unit 当前为 `failed/failed`，未执行 `reset-failed`。
- 最小化日志确认直接失败原因是 uvicorn 无法绑定 `0.0.0.0:8200`，错误分类为端口冲突。
- 8200 由旧 uvicorn 进程 PID 4070714 占用；该 PID 是快照，必须实时复核。
- 旧 uvicorn 的父进程为 1，属于 `/system.slice/tat_agent.service`，位于 `fund-advisor-backend.service` 控制组之外。
- 旧 uvicorn 的工作目录是生产 Git 工作区内的 `fund-advisor`；停止后 7 次 `/health` 均返回 HTTP 200。
- 前端 systemd 服务为 `active/running`、累计重启为 0，8201 根页面返回 HTTP 200；这不等于公网访问链路已经完整验收。
- OpenClaw 进程存在，用户级监控 cron 有 1 个匹配项；尚无证据证明它直接启动 PID 4070714。
- 未发现匹配的 systemd timer、活动 Git 拉取进程或常见文件 watcher。

### 3.4 资源与数据库

- 根磁盘使用率约 66%，内存与交换空间仍有余量，当前没有资源耗尽证据。
- `mysqld` 进程存在，但未确认 TCP 3306 监听；本轮不连接数据库。
- 常用兼容备份工具仍未发现，数据库备份与恢复门禁继续阻塞正式生产发布。

## 4. 根因分层

### 4.1 已确认的直接根因

存在一个不属于当前 systemd unit 控制组的旧 uvicorn 进程占用 8200。systemd 每 10 秒启动新实例，新实例因端口已占用而退出，形成无限自动重试。

### 4.2 已确认的运行环境漂移

systemd 工作目录属于生产 Git 工作区，但 uvicorn/虚拟环境来自历史目录。代码目录、解释器目录和进程控制权没有形成单一发布单元。

### 4.3 端口问题解决后可能出现的第二故障

服务器当前缺少 `backend/engine_bridge.py`，运行环境不能解析 `engine.analyzer`。旧进程当前健康不证明重新启动后的新进程可以完成导入和应用启动。

因此，未经过 staging 证明前，禁止先终止旧健康进程再尝试启动新版本。

## 5. 永久保护边界

- 不处理、暂存、清理、还原或覆盖 5 个第四组文件。
- 不调整策略参数，不重写已验收 P0，不开始 P1。
- 不在服务器生产脏工作区执行 `pull`、`checkout`、`reset`、`clean`、`stash` 或覆盖式同步。
- 不读取或输出服务器 `.env` 值、数据库连接串、Token、密码、私钥、真实持仓或完整日志。
- 不操作 MySQL，不重启 MySQL，不修改数据库或生产数据。
- 不终止旧 uvicorn，不修改 OpenClaw、cron、systemd unit 文件或生产代码，除非进入对应阶段并获得该阶段的明确授权。
- 不把停止 systemd 自动重试解释为授权部署、授权切流或授权停止旧健康后端。

## 6. 第一阶段：最小只读准入复核

Luna 切换接手后只做本节，然后汇报并等待确认。不要重复 `05` 的广泛调查。

> 完成状态：Luna 已于 2026-09-03 完成本阶段，结果符合第二阶段前提。除第二阶段写操作前的同窗口最后检查外，不再重复本阶段。

### 6.1 本地与 GitHub

只读确认：

- 当前分支、HEAD、跟踪分支和 GitHub 实际分支仍为 `5f8bc18683c807dd0ef18b3b35735a7b4cffd016`。
- 暂存区为空。
- 差异集合严格等于 24 个已知候选文件加 5 个第四组文件。
- 5 个第四组文件内容和哈希没有变化。

出现新文件、新暂存内容、SHA 漂移或第四组文件变化时立即停止。

### 6.2 服务器与控制链

只读确认：

- 生产 Git SHA 和 3 个未提交热修文件没有变化。
- `fund-advisor-backend.service` 仍在自动重试，`NRestarts` 仍递增。
- 8200 仍由唯一旧 uvicorn 占用，记录实时 PID、父进程和控制组归属。
- 旧进程仍不属于 `fund-advisor-backend.service` 控制组。
- 旧进程 `/health` 仍正常。
- 前端服务仍稳定。
- OpenClaw、cron、systemd timer、Git 进程和 watcher 状态没有出现新的并发控制证据。
- 数据库进程和服务器资源没有出现新的异常。

不要读取完整日志。除非状态与基线不符，只保留最近最小化端口错误分类即可。

### 6.3 第一阶段停止门

完成后只汇报：

- 是否满足第二阶段前提。
- 实时旧 uvicorn PID、8200 归属、健康状态和 systemd 重启计数。
- 执行 `systemctl stop fund-advisor-backend.service` 是否预计会影响旧进程。
- 第二阶段精确动作、风险、验证和回滚。

未获得用户明确确认前，不执行任何 `systemctl` 写操作或进程信号。

## 7. 第二阶段：停止失败的自动重试

> 完成状态：Luna 已于 2026-09-03 完成本阶段。唯一写操作成功；未触发回滚，禁止重复执行。

只有用户明确确认以下完整授权后才执行：

> 停止 `fund-advisor-backend.service` 的失败自动重试；保留旧健康 uvicorn；若健康接口意外失效，允许按本节回滚。不得修改代码、OpenClaw、cron、数据库或旧 uvicorn。

### 7.1 执行前最后检查

在同一操作窗口内再次确认：

- 8200 的实时占用 PID 与第一阶段一致。
- 该进程仍在 backend unit 控制组之外。
- `/health` 正常。
- systemd 新实例没有短暂成为 8200 的实际占用者。
- 没有 OpenClaw 或其他执行端正在进行发布、重启或文件写入。

任一条件不成立就停止，不执行 `systemctl stop`。

### 7.2 唯一计划写操作

本阶段唯一常规写操作是：

```bash
# 停止失败的 systemd 自动重试；不直接向旧健康 uvicorn 发送信号。
systemctl stop fund-advisor-backend.service
```

不要同时执行 `disable`、`mask`、`daemon-reload`、unit 编辑、进程终止或 OpenClaw/cron 修改。

### 7.3 立即验证

操作后连续观察至少 60 秒，只读确认：

- backend unit 不再处于 `activating/auto-restart`；`inactive/dead` 或保留 `failed/failed` 均须结合稳定的 `NRestarts` 判断，不为清除展示状态擅自运行 `reset-failed`。
- `NRestarts` 不再递增。
- 旧 uvicorn PID 未变化，仍唯一占用 8200。
- `/health` 连续成功。
- 前端服务状态没有变化。
- OpenClaw 或 cron 没有重新启动 backend unit。
- 没有新的服务错误或资源异常。

如果 OpenClaw 或其他控制链重新启动 unit，只报告证据并停止。不得自行暂停 OpenClaw 或修改 cron。

### 7.4 回滚

若 `systemctl stop` 后旧进程意外消失或 `/health` 失败：

1. 立即停止扩大操作，不终止其他进程，不修改代码和配置。
2. 只在用户对第二阶段的确认明确包含回滚授权时执行：

```bash
# 恢复原 systemd 控制链；这可能重新进入端口冲突循环，仅作为恢复到操作前状态的应急动作。
systemctl start fund-advisor-backend.service
```

3. 重新检查 unit、端口和健康接口，汇报结果。
4. 即使回滚失败，也不得手工启动 uvicorn、复制虚拟环境或修改 unit。

### 7.5 第二阶段汇报

必须汇报：

- 实际执行时间和唯一写操作。
- 操作前后 unit 状态、重启计数、8200 占用 PID 和健康接口。
- OpenClaw/cron 是否干预。
- 是否执行回滚。
- 本地和服务器文件是否修改、数据库是否操作。

第二阶段成功只表示生产临时稳定，不表示正式部署完成。

实际结果：backend unit 保留 `failed/failed`，但 61 秒内 `NRestarts=6716` 未递增；旧 uvicorn、8200、健康接口、前端、OpenClaw、cron 和 `tat_agent.service` 均保持稳定。未执行 `reset-failed`、应急回滚或其他写操作。

## 8. 第三阶段：恢复本地发布包和 staging

第二阶段已经成功，但仍需用户再次确认，才恢复 `04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md` 第二阶段及之后的流程。

恢复顺序：

1. 在本地生成 Linux/Python 3.12 依赖锁。
2. 在干净提交快照中完成两套 Python 测试、后端镜像、前端 `npm ci`/生产构建和 Compose 验证。
3. 按 `04` 白名单和三提交方案固化到新的 `codex/` 分支，汇报后等待独立的 GitHub 推送确认。
4. 获得推送确认后形成 GitHub 明确 SHA，再等待独立的服务器 staging 确认。
5. 获得 staging 确认后，使用明确完整 SHA 在生产工作区之外创建隔离 staging。
6. staging 只使用合成 MySQL、独立卷、独立凭据和回环端口；关闭调度、启动净值回补、邮件与生产外部凭据。
7. 验证 `backend.engine_bridge`、`engine.analyzer`、后端健康接口、前端页面和关键虚构业务流程。

本阶段不操作生产旧 uvicorn、生产 systemd、生产 Git 工作区或生产数据库。

## 9. 第四阶段：生产单实例切换准备

只有 staging 验收通过后才规划，不在本轮 Luna 首次执行范围内。

正式切换前必须另外满足：

- 发布源是 GitHub 上已验证的明确完整 SHA。
- 生产 3 个热修已包含在目标 SHA，且有不覆盖脏工作区的迁移方案。
- Python/uvicorn 与代码位于同一可复现发布单元，不再复用历史虚拟环境路径。
- OpenClaw、cron 和 systemd 的暂停/恢复负责人明确。
- 数据库备份与恢复门禁满足；即使没有数据库迁移，也不能假设维护窗口可以忽略数据库安全。
- 旧健康 uvicorn 的停止方式、验证方法和失败恢复方式已单独获得确认。

建议切换顺序为：保留旧实例 → 部署并验证新发布单元的非生产端口 → 确认切换窗口 → 停止旧实例 → 由唯一 systemd unit 接管 8200 → 验证 → 恢复必要自动化。

不得先停止旧健康实例，再临时排查新版本依赖。

## 10. 立即停止条件

出现任一情况立即停止并汇报：

- 本地、GitHub、服务器 SHA 或差异集合与基线不符。
- 5 个第四组文件或服务器 3 个热修文件发生新变化。
- 8200 占用者、父进程或控制组归属发生变化。
- 旧 `/health` 失败、前端异常或数据库进程异常。
- OpenClaw、cron、systemd timer 或另一执行端开始写文件、重启或替换进程。
- `systemctl stop` 可能终止旧健康进程，或无法说明回滚路径。
- 需要输出秘密、真实持仓、数据库内容或完整日志才能继续。
- 需要修改 unit、OpenClaw、cron、生产代码或数据库才能完成当前阶段。
- 任何命令的只读或写入边界无法确认。

## 11. 已执行的第二阶段确认指令

> 以下仅保留为审计记录，第二阶段已经完成，不得再次发送或执行。当前下一执行包见 `04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md` 第 10 节。

```text
确认执行 E:\myfund11111 的生产后端稳定化第二阶段，并同时授权本节规定的应急回滚。

先完整阅读 AGENTS.md、00_LUNA_START_HERE.md、LUNA_HANDOFF.md、
02_LUNA_SERVER_RELEASE_READINESS.md、03_LUNA_OPENCLAW_COLLABORATION.md、
04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md、05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md、
docs/operations/SYSTEM_ARCHITECTURE.md、docs/operations/RUNBOOK.md、
docs/operations/OPENCLAW_CODEX_COLLABORATION.md、ops/README.md 和
06_LUNA_PRODUCTION_STABILIZATION.md。

第一阶段只读准入复核已经通过，不要重复广泛调查。严格按
06_LUNA_PRODUCTION_STABILIZATION.md 第七节执行：先在同一操作窗口完成 7.1 的最后
只读检查；只有实时状态仍符合基线时，执行唯一常规写操作
systemctl stop fund-advisor-backend.service。不要停止、终止或向 PID 4070714 发送信号，
不要修改或停止 tat_agent.service。

执行后连续观察至少 60 秒，确认 backend unit 为 inactive/dead、重启计数不再递增、
旧 uvicorn PID 4070714 仍唯一占用 8200、/health 连续返回 HTTP 200、前端服务与 8201
根页面正常，并确认 OpenClaw、cron 或 tat_agent 没有重新拉起 backend unit。

本条同时授权应急回滚：如果 systemctl stop 后旧 uvicorn 意外消失或 /health 失败，
立即停止扩大操作，并只执行一次 systemctl start fund-advisor-backend.service 恢复原
systemd 控制链；随后只读复核并汇报。即使回滚失败，也不要手工启动 uvicorn、修改
unit、复制虚拟环境或终止其他进程。

如果 7.1 任一前提发生漂移，不执行写操作，直接汇报。不要修改本地或服务器文件，
不要创建分支、锁文件、暂存、提交或推送，不要修改 OpenClaw、cron、tat_agent、unit
文件或数据库。不要处理 5 个第四组文件，不调整策略参数，不重写 P0，不恢复 04，
不部署 staging，不切生产流量。完成第二阶段后汇报并等待下一次确认。
```

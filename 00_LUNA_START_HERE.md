# Luna 从这里开始

> 更新日期：2026-09-03
> 当前任务：`06_LUNA_PRODUCTION_STABILIZATION.md` 第二阶段已经完成，失败的 backend systemd 自动重试已停止且旧健康后端继续服务；等待用户授权恢复 `04` 第二阶段的本地发布包收口。

## 1. 文档读取路由

新任务、应用重启、上下文恢复不确定或核心文档发生变化时，按顺序完整阅读以下 5 份核心材料：

1. `AGENTS.md`：仓库、Git、秘密、服务器和数据库的最高优先级边界。
2. 本文件 `00_LUNA_START_HERE.md`：当前阶段、可信基线和下一任务入口。
3. `LUNA_HANDOFF.md`：最新本地、GitHub、服务器和 OpenClaw 状态。
4. `docs/operations/CODEX_LUNA_ORCHESTRATION.md`：Sol 指挥、Luna 执行、额度优化和后台调度规范。
5. 当前阶段执行令：目前是 `04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md`。

其余文档按任务读取，不再每轮全部重读：

- 本地发布包收口：按 `04` 第二节指定的章节读取运维资料。
- 首次进入服务器或 staging 写阶段：完整阅读 `docs/operations/OPENCLAW_CODEX_COLLABORATION.md`、`docs/operations/SYSTEM_ARCHITECTURE.md`、`docs/operations/RUNBOOK.md` 和 `ops/README.md`。
- P0 正确性实现或验收发生变化：读取 `01_LUNA_P0_CLOSEOUT.md` 和 `docs/development/P0_ACCEPTANCE_REPORT.md`；否则只作历史证据，不重复读取。
- 服务器热修、OpenClaw 控制链或后端故障基线发生冲突：再读取 `02`、`03`、`05`、`06` 对应章节，不因它们存在就全部重读。
- 业务语义确需复核：再读取 `DEVELOPMENT_PLAN_PROFITABILITY.md`、`DEVELOPMENT_DECISIONS.md` 和 `DEVELOPMENT_PORTFOLIO_SCALING.md`。

同一个 Luna 任务连续执行且核心文档未变化时，只重读本文件、`LUNA_HANDOFF.md`、当前阶段发生变化的章节和实时差异。不得为了节省上下文省略授权边界、保护文件校验或状态切换前的实时复核。

## 2. 当前可信基线

- 本地分支：`codex/p0-server-readiness`。
- 本地与 GitHub 目标提交：`5f8bc18683c807dd0ef18b3b35735a7b4cffd016`。
- `5f8bc18` 已包含 P0 收口提交和服务器 3 项模型调用热修。
- 当前工作区共有 25 个已知 staging/文档候选文件和 5 个第四组文件；暂存区为空。
- 本地 5 个第四组既有改动禁止处理、暂存、清理或覆盖。
- 本轮文档差异包含交接入口、当前未提交的五份阶段执行令（`02` 至 `06`）、两份长期协同规范以及同步更新的架构/运维说明，尚待按白名单收口。
- 服务器生产工作区仍位于 `main` 的 `afc19e9b203141e8e604fc3f1b9f5dd438637a81`，并保留 3 个未提交热修文件。
- OpenClaw 仍有运行进程；前端继续由 systemd 管理。backend unit 的配置仍是 `Restart=always`，但 unit 已停止，不再自动重试。
- 第一阶段短时采样未观察到热修文件继续写入，但这不等于 OpenClaw 已完全退出控制。
- 生产 MySQL 进程存在，兼容备份工具和恢复证据仍未满足生产发布门禁。
- 最近一次完整验证记录为：分析引擎 165 项通过、后端 5 项通过、前端生产构建通过；切换模型后仍需按任务范围重新核对。
- 本轮已修正测试中的历史 OpenClaw 绝对路径、后端 monorepo 镜像上下文、前端 `npm ci` 安装方式，并新增 staging Compose/环境模板。
- 本轮未生成 Linux Python 锁文件；生产依赖可复现性仍是 staging 验收门禁。
- Luna 已执行唯一写操作 `systemctl stop fund-advisor-backend.service`；随后观察 61 秒，累计重启计数稳定在 6716，不再递增。
- backend unit 当前为 `failed/failed`，但已经停止 `auto-restart`；未执行 `reset-failed`、`disable`、`mask` 或 unit 修改。
- 8200 当前由旧 uvicorn PID 4070714 唯一占用；其父进程为 1，属于 `/system.slice/tat_agent.service`，不属于 backend unit，61 秒内 7 次 `/health` 均返回 HTTP 200。
- systemd 工作目录已确认是生产 Git 工作区内的 `fund-advisor` 子目录，但 uvicorn 虚拟环境仍来自另一套历史路径。
- 服务器当前缺少 `backend/engine_bridge.py`，静态模块定位无法解析 `backend.engine_bridge` 和 `engine.analyzer`；这可能是端口问题后的第二阻塞。
- 前端服务稳定运行、重启计数为 0，8201 根页面返回 HTTP 200；OpenClaw 进程和一个用户级监控 cron 仍存在，尚无证据证明其直接启动旧 uvicorn。

以上是交接基线，不是永久事实。任何分支、SHA、文件清单、进程或服务状态发生漂移，都必须停止并先汇报。

## 3. Luna 的下一任务

1. `06` 第一、第二阶段已经完成，不再执行 `systemctl stop`，也不为美化状态擅自运行 `reset-failed`。
2. 等待用户在 Sol 指挥任务中明确确认恢复 `04` 第二阶段；确认后由 Sol 后台把单阶段执行包发送给现有 Luna，用户无需手工复制。
3. `04` 第二阶段只完成本地分支、Linux 锁、干净测试/构建和三个本地提交；完成后汇报并等待独立的 GitHub 推送确认。
4. GitHub 推送完成后，再进行服务器 staging 写入前的只读复核并等待独立的 staging 部署确认。
5. staging 验收、备份与回滚门禁满足后，才能另行规划生产单实例切换。

未获得对应阶段确认前，不得创建分支、生成锁、暂存、提交、推送、执行 systemd 写操作、向进程发送信号、部署 staging、覆盖 OpenClaw 生产工作区或切换生产流量。不得重复改写 P0、调整策略参数或处理 5 个第四组文件。

系统只提供建议。只有用户确认实际操作及平台成交信息后才同步持仓；用户未操作时，持仓保持原样。

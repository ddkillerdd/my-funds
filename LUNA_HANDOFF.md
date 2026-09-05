# Luna 开发接手入口

> 交接日期：2026-09-05
> 交接目标：阶段 A、B1、B2、C、D 已收口；下一任务按 `13_LUNA_HOLDING_CORRECTNESS_FINAL_GATE.md` 完成文档和提交前验证，未确认前不提交、推送或部署。

## 0. 2026-09-05 当前权威交接

本节取代下文旧的“当前状态”和“下一阶段任务”；旧内容只作历史证据。

- 当前本地分支为 `codex/holding-ingestion-correctness`，四组本地提交已完成，暂存区为空；该正确性分支尚未推送。
- 服务器生产外 staging 已按该 SHA 部署，后端、前端与独立 MySQL 健康；仅绑定回环端口，scheduler、启动 NAV 回补、外部模型和邮件关闭。
- 用户通过 staging 快捷导入测试记录后，页面出现占位基金名称、缺失最新净值和零份额；这批测试数据不得复制到本地或输出明细。
- 只读代码审查确认问题集中于：按需基金信息补全、零份额安全修复、统一持仓身份与账本、Excel/ZIP 来源内清仓、事务、解析和上传安全。
- 当前工作区仍有五个原第四组差异。用户已允许本次修复修改其中三个服务文件：
  - `fund-advisor/backend/services/calendar_service.py`
  - `fund-advisor/backend/services/excel_parser.py`
  - `fund-advisor/backend/services/nav_service.py`
- 上述三个文件现有差异仅增加 `from __future__ import annotations`，必须保留并允许在其上继续修改。
- 以下两个文件仍不得编辑、还原、暂存或提交：
  - `fund-analyzer/tests/test_position.py`
  - `fund-analyzer/tests/test_screener.py`
- 用户已授权本地正确性修复；执行分支为 `codex/holding-ingestion-correctness`。当前阶段允许修改 `07` 白名单并运行测试，不允许暂存、提交、推送、更新服务器 staging、执行服务器迁移或切生产。
- 总执行令：`07_LUNA_HOLDING_INGESTION_CORRECTNESS.md`。阶段 A 至 D 已分别在 `08` 至 `12` 收口；当前准入令为 `13_LUNA_HOLDING_CORRECTNESS_FINAL_GATE.md`。不得跳过确认门自行提交、推送或部署。

## 1. 已完成事项

- P0 四组跨层正确性问题已修复并完成回归验收。
- 开发环境与引擎桥接、P0 正确性、文档与运维边界已经拆分提交。
- 服务器 3 项模型调用热修已经固化为 `5f8bc18`，并推送到 GitHub 分支 `codex/p0-server-readiness`。
- 第一阶段 OpenClaw 控制范围调查已经完成，调查过程未修改本地或服务器。
- 已确认 OpenClaw 仍有运行进程，生产服务由 systemd 管理且设置 `Restart=always`。
- 短时并发写入采样未发现 3 个热修文件继续变化；该结果只代表采样窗口。
- 本轮已完成本地 staging 可复现性修复：测试路径移除历史 OpenClaw 绝对路径，后端镜像纳入引擎目录，前端改用 `npm ci`，并新增隔离 staging 模板。
- `04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md` 已规定下一阶段的白名单、Linux 锁、干净快照验证、三提交拆分和服务器 staging 二次确认门。
- `05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md` 的只读诊断已完成，确认直接根因是旧 uvicorn 占用 8200，systemd 新实例持续绑定失败。
- `06_LUNA_PRODUCTION_STABILIZATION.md` 已规定生产临时稳定、验证、回滚及恢复 `04` 的分阶段授权门。
- `06` 第一阶段最小只读准入复核已经通过。
- `06` 第二阶段已经完成：唯一写操作为 `systemctl stop fund-advisor-backend.service`，未向旧 uvicorn 发送信号，未修改 `tat_agent.service`。
- 停止后观察 61 秒，旧 uvicorn PID 4070714 始终唯一占用 8200，7 次 `/health` 均为 HTTP 200，前端和 8201 正常，累计重启计数稳定在 6716。
- backend unit 当前保留 `failed/failed` 状态但不再自动重试；未执行 `reset-failed`，也未触发应急回滚。
- 已新增 `docs/operations/CODEX_LUNA_ORCHESTRATION.md`，长期采用“用户在 Sol 授权、Sol 后台调度、Luna 单独执行、OpenClaw 遵守生产边界”的方式，用户无需手工转发结果。

## 2. 当前状态

### 本地与 GitHub

- 当前分支：`codex/p0-server-readiness`。
- 当前 `HEAD`：`5f8bc18683c807dd0ef18b3b35735a7b4cffd016`。
- `origin/codex/p0-server-readiness` 与本地 `HEAD` 一致。
- 暂存区为空。
- 下列 5 个第四组既有改动必须原样保留：
  - `fund-advisor/backend/services/calendar_service.py`
  - `fund-advisor/backend/services/excel_parser.py`
  - `fund-advisor/backend/services/nav_service.py`
  - `fund-analyzer/tests/test_position.py`
  - `fund-analyzer/tests/test_screener.py`
- 当前工作区共有 25 个已知 staging/文档候选文件和 5 个第四组文件，暂存区仍为空。
- 交接入口、当前未提交的五份阶段执行令（`02` 至 `06`）、两份长期协同规范以及同步更新的架构/运维说明仍属于本轮文档工作，不得与第四组文件混合提交。

### 服务器与 OpenClaw

- 生产工作区仍在 `main` 的 `afc19e9b203141e8e604fc3f1b9f5dd438637a81`。
- 服务器仍有 3 个未提交热修文件；其功能已在 GitHub 的 `5f8bc18` 中固化，但生产工作区尚未迁移到该提交。
- 只读巡检发现 OpenClaw 相关进程存在，未发现正在执行的 Git 拉取、常见文件监控器或 Codex 进程。
- 用户定时任务涉及 OpenClaw；未发现直接指向本项目的 Git 同步或服务重启条目。
- 后端 unit 配置仍为 `Restart=always`，但已执行停止；累计重启计数在 61 秒观察期内稳定为 6716，不再产生失败重试。
- 生产数据库进程存在；常用兼容备份客户端尚未发现，生产发布仍被备份与恢复证据阻塞。
- 本地验证结果：分析引擎 165 项通过、后端 5 项通过、前端生产构建通过、3 份 Compose YAML 解析通过；`npm ci` dry-run 仍受现有 `node_modules` 隐藏锁文件 `EPERM` 阻塞。
- 最小化日志确认新 uvicorn 曾因 8200 已占用退出；停止 backend unit 后，端口仍由旧 uvicorn PID 4070714 唯一占用。
- 旧 uvicorn 的父进程为 1，属于 `/system.slice/tat_agent.service`，位于 backend unit 控制组之外，工作目录属于生产 Git 工作区；停止后的 7 次 `/health` 均返回 HTTP 200。
- backend unit 当前为 `failed/failed` 而不是 `inactive/dead`，但没有继续自动重试；该状态只作记录，不授权执行 `reset-failed`。
- 后端 systemd 工作目录已确认是生产 Git 工作区的 `fund-advisor` 子目录；但 uvicorn 虚拟环境来自另一套历史路径。
- 服务器缺少 `backend/engine_bridge.py`，静态模块定位无法解析 `backend.engine_bridge` 和 `engine.analyzer`；不得在未完成 staging 前终止旧健康进程。
- 前端服务稳定运行且累计重启为 0，8201 根页面返回 HTTP 200；OpenClaw 进程和一个用户级监控 cron 仍存在，尚无直接证据表明其启动旧 uvicorn。

## 3. 权威来源与协同边界

- GitHub 上的明确提交 SHA 是正常开发与发布代码来源。
- 服务器运行状态是过渡期生产事实来源，但服务器脏工作区不能作为正式发布包。
- OpenClaw 继续承担生产运行观察或经确认的紧急操作；Codex/Luna 负责本地审查、开发、测试和 Git 固化。
- 同一时间、同一文件只能由一个执行端修改。来源不明或并发写入时立即停止。
- 真实数据库、上传文件、服务器 `.env`、日志和凭据只留在服务器，不复制到本地或 staging。

跨任务调度规则见 `docs/operations/CODEX_LUNA_ORCHESTRATION.md`；生产协同规则见 `docs/operations/OPENCLAW_CODEX_COLLABORATION.md`。

## 4. 下一阶段任务

本地持仓正确性发布包已按白名单拆分为四个本地提交，但尚未推送。下一步等待独立 GitHub 推送确认：

1. 等待独立 GitHub 推送确认。
2. 推送后只读复核服务器 staging 准入；创建服务器目录、配置、容器、卷和合成数据库必须再获独立确认。

当前尚未获得 `04` 第二阶段确认。不得创建分支、生成锁、暂存、提交、推送、拉取镜像或创建临时环境；不得执行新的 systemd 写操作、终止旧 uvicorn、修改 OpenClaw、cron、tat_agent 或操作数据库。

## 5. 必须保持的业务边界

- 最大可接受回撤暂定为 20%，本轮不调整。
- 系统只提供建议，不自动下单。
- 只有用户确认实际完成或部分完成交易后，才能按真实成交信息同步持仓。
- 用户没有操作时，持仓保持原样。
- 不重复重写已经验收的 P0 实现，不开始 P1，不顺手处理第四组文件。
- 本机 Docker Hub 出站连通性仍不可达；staging 镜像门禁改由明确 GitHub SHA 在生产工作区之外的服务器完成，本机阻塞不构成生产发布验收。
Staging-only 基线例外：detached 快照中的 test_position.py::test_action_amount_with_total_mv 与 test_screener.py::test_base_weights_loaded 允许登记为已知失败；这不构成全绿验收，生产发布仍被阻塞。

## 6. 2026-09-05 最终准入第一阶段实际状态

- A-D 持仓正确性实现保持未提交工作区状态；最终准入文档、项目说明和变更记录已补齐实际检查证据。
- `git diff --check` 通过；变更/新增 22 个 Python 文件 AST 通过；前端纯逻辑测试 7/7 通过。
- 指定 npm 构建已在允许启动 esbuild 子进程的执行环境中通过（Vite 6.4.1，2103 个模块，10.67 秒，仅有大于 500 kB chunk 警告）；此前受限沙箱的 `spawn EPERM` 不作为代码/发布阻塞。后端与分析引擎 pytest 首个错误仍为 Bundled Python 缺少 `pytest`。Python 全量测试、迁移和 staging 尚未验收。
- 精确提交白名单及四组建议已写入 `13_LUNA_HOLDING_CORRECTNESS_FINAL_GATE.md`；两个受保护 `fund-analyzer/tests` 文件排除且哈希未变。
- 当前已完成本地暂存/提交流程；不允许推送或任何服务器/生产操作，等待独立 GitHub 推送确认。

## 7. 2026-09-05 c5444b63 staging 回归修复交接

- c5444b63 镜像构建成功；合成 MySQL 曾健康运行，空库迁移至 `b1c2d3e4f5a6`，纯合成旧 schema `a1b2c3d4e5f6` 升级至 head 成功。
- 初次目标快照后端 68 通过/4 失败、分析引擎 163 通过/2 个已登记保护失败；两文件修复后定向测试 4/4、后端完整测试 72/72 均通过，显式带 `-p no:cacheprovider`。
- c544 staging MySQL 已停止；runtime、镜像、网络、卷和合成数据保留，backend/frontend 未启动。生产、旧 6a774457 staging、OpenClaw、systemd、cron 和生产数据库未改。
- 下一步按包含两文件修复的新提交 SHA 重建独立 staging；迁移、全量测试和运行验收完成前，不宣称生产可用。

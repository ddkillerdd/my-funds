# Luna Codex 与 OpenClaw 协同及隔离 staging 执行令

> 编写日期：2026-09-02
> 本地仓库：`E:\myfund11111`
> 当前阶段：OpenClaw 调查、协同规范和 staging 可复现性修复已完成；生产后端异常优先转入 `05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md`
> 执行角色：Luna 负责操作；本文件限定 Codex、OpenClaw、GitHub 和服务器之间的职责与停止条件

## 1. 背景与目标

本项目此前主要由 OpenClaw 直接在服务器工作区开发、运行和管理。现在新增本地 Codex 开发与 GitHub 发布链路，必须防止两个执行端同时改写同一工作区、相互覆盖代码或重复重启服务。

本轮目标：

1. 只读识别 OpenClaw 对生产工作区、Git、systemd、定时任务和服务恢复的实际控制范围。
2. 建立 Codex 与 OpenClaw 的协同协议和 Git 分支边界。
3. 确认当前发布 SHA 可以在 Linux 环境独立复现。
4. 在不触碰 OpenClaw 生产工作区的前提下设计并部署隔离 staging。
5. 通过 SSH 隧道让用户测试 staging，不切生产流量。

本执行令是 `02_LUNA_SERVER_RELEASE_READINESS.md` 的协同补充，不取消其中的生产数据库备份、回滚和生产切换门禁。

## 2. 当前基线

2026-09-02 第一阶段只读核对得到：

- 本地分支：`codex/p0-server-readiness`
- 本地及 GitHub SHA：`5f8bc18683c807dd0ef18b3b35735a7b4cffd016`
- `5f8bc18` 已包含服务器 3 个模型调用热修
- 本地工作区仍有 5 个未提交的第四组既有改动：
  - `fund-advisor/backend/services/calendar_service.py`
  - `fund-advisor/backend/services/excel_parser.py`
  - `fund-advisor/backend/services/nav_service.py`
  - `fund-analyzer/tests/test_position.py`
  - `fund-analyzer/tests/test_screener.py`
- 本轮文档差异包括交接入口、当前未提交的四份阶段执行令（`02` 至 `05`）、正式协同规范以及同步更新的架构/运维说明
- `docs/operations/OPENCLAW_CODEX_COLLABORATION.md` 已形成正式协同规范，所有文档仍待独立审查是否提交
- 最近一次验证：分析引擎 165 项、后端 5 项测试通过，前端生产构建通过
- 服务器生产工作区仍由 OpenClaw 历史流程管理，仍停在 `afc19e9` 加 3 个未提交热修的状态
- OpenClaw 相关进程仍存在；未发现 Codex、常见文件监控器或正在执行的 Git 拉取进程
- 用户定时任务涉及 OpenClaw；后端和前端 systemd 单元与项目/OpenClaw 管理链有关
- 后端和前端巡检时均为 `active/running`，但设置 `Restart=always`
- 对 3 个热修文件的短时采样未观察到并发写入；该结论不证明 OpenClaw 已退出控制
- 生产 MySQL 进程存在，但兼容数据库备份客户端与恢复证据仍未满足

该基线只用于发现漂移。Luna 必须重新执行只读检查。

## 3. 必须完整阅读

开始操作前按顺序完整阅读：

1. `E:\myfund11111\AGENTS.md`
2. `E:\myfund11111\00_LUNA_START_HERE.md`
3. `E:\myfund11111\LUNA_HANDOFF.md`
4. `E:\myfund11111\01_LUNA_P0_CLOSEOUT.md`
5. `E:\myfund11111\02_LUNA_SERVER_RELEASE_READINESS.md`
6. `E:\myfund11111\docs\operations\SYSTEM_ARCHITECTURE.md`
7. `E:\myfund11111\docs\operations\RUNBOOK.md`
8. `E:\myfund11111\ops\README.md`
9. 本文件 `E:\myfund11111\03_LUNA_OPENCLAW_COLLABORATION.md`

若文档冲突，以 `AGENTS.md`、用户最新指令和更严格的服务器安全边界为准。

## 4. 双端协同原则

### 4.1 权威来源

- 过渡期内，服务器运行状态是生产事实来源。
- 正常开发和发布以 GitHub 上的明确提交 SHA 为代码来源。
- OpenClaw 留在服务器工作区的热修必须尽快形成独立 Git 提交，不能长期作为唯一副本。
- 真实数据库、上传文件、服务器 `.env` 和运行日志始终留在服务器。

### 4.2 分支边界

- Codex 本地开发使用 `codex/<任务>` 分支。
- OpenClaw 开发使用 `openclaw/<日期>-<任务>` 分支。
- `main` 只接受已经审查、测试和具备回滚证据的提交。
- 两个执行端不得同时直接修改 `main`，不得强制推送。
- 同一个文件由一个执行端负责修改；需要交叉修改时，先提交并通过 Git 合并或 cherry-pick 交接。

### 4.3 开工门禁

每次开始开发前必须记录：

- 执行端：Codex 或 OpenClaw。
- 任务范围和禁止处理的文件。
- 基础分支和基础 SHA。
- 计划修改的文件。
- 当前服务器工作区是否干净。
- 是否存在另一端正在执行的任务、定时任务或自动恢复动作。

发现同一文件存在并发修改或来源不明的脏差异时停止，不猜测覆盖顺序。

### 4.4 交接门禁

每次交接必须提供：

- 分支名和完整提交 SHA。
- 修改文件清单和未修改边界。
- 测试、构建和敏感信息检查结果。
- 服务器是否被修改、服务是否重启、数据库是否操作。
- 尚未完成事项和回滚方式。

禁止使用未提交工作区、补丁聊天文本或服务器目录覆盖作为正式交接方式。

## 5. 第一阶段：只读识别 OpenClaw 控制范围

本阶段只允许读取状态，不允许修改本地文件、服务器文件、Git、服务、计划任务或数据库。

### 5.1 本地与 GitHub 核对

```powershell
# 核对当前协同分支、目标 SHA 和剩余未提交文件。
git -C 'E:\myfund11111' status --short --branch
git -C 'E:\myfund11111' rev-parse HEAD
git -C 'E:\myfund11111' rev-parse origin/codex/p0-server-readiness
git -C 'E:\myfund11111' diff --name-status
git -C 'E:\myfund11111' ls-files --others --exclude-standard
```

预期代码差异严格等于已知 5 个第四组文件；文档差异只允许是本轮列明的交接与协同文档。出现其他代码文件时立即停止。

### 5.2 OpenClaw 只读调查

使用 `ops/.env` 和既有 SSH 安全参数，只读确认：

- OpenClaw 当前是否有运行中的任务或代理进程。
- OpenClaw 是否配置自动拉取、自动提交、自动部署、文件监控或失败恢复。
- OpenClaw 是否通过 cron、systemd timer、systemd service、容器或其他守护进程管理本项目。
- OpenClaw 管理的生产工作区和 systemd 服务之间的关系。
- 当前生产后端、前端由哪个进程启动，是否会被 OpenClaw 自动拉起或覆盖。
- 最近是否有 OpenClaw 正在写入项目文件；只返回时间、文件名和聚合结论，不输出完整日志。
- OpenClaw 是否保存任务状态、工作树锁或交接文件；只记录路径和用途，不读取秘密。
- 当前 Git 分支、HEAD、脏文件和远程关系是否仍符合已知基线。

允许读取：

- 进程名、PID、启动时间和父进程关系。
- systemd 单元名、timer 名、WorkingDirectory、ExecStart、ActiveState 和 SubState。
- crontab 中与项目或 OpenClaw 相关的命令名称和时间表达式；命令参数必须脱敏。
- Git 状态、提交 SHA、文件名、差异统计和文件修改时间。

禁止读取或输出：

- OpenClaw、服务器或应用中的 Token、Cookie、密码、私钥和完整环境变量。
- 完整 OpenClaw 对话、任务日志、模型提示、真实持仓和数据库数据。
- 服务器私密地址、连接串和邮件凭据。

### 第一停止条件

出现任一情况立即停止并报告：

- OpenClaw 正在执行本项目任务或持续写入生产工作区。
- 存在自动拉取、覆盖、回滚或重启机制，但无法确认触发条件。
- 当前分支、SHA、脏文件或服务状态与基线不一致。
- 后端仍处于自动重启或出现新的服务异常。
- 只读调查需要暴露秘密才能继续。

第一阶段结束后必须向用户汇报并等待确认，不得直接创建协同配置或 staging。

### 5.3 第一阶段实际结果

本阶段已经完成，只读结果如下：

- 本地与 GitHub 均指向 `5f8bc18683c807dd0ef18b3b35735a7b4cffd016`，暂存区为空。
- 本地代码差异仍严格等于 5 个第四组文件，另有本轮执行文档差异。
- 服务器仍位于 `afc19e9b203141e8e604fc3f1b9f5dd438637a81`，脏文件仍严格等于 3 个已知热修文件。
- 发现 6 个 OpenClaw 相关进程，未发现 Codex 进程、常见文件监控器或活动中的 Git 拉取/获取进程。
- 用户定时任务包含 OpenClaw 项，但未发现直接针对本项目的 Git 同步或服务重启项。
- 后端和前端服务当前为 `active/running`，但均设置 `Restart=always`。
- 3 个热修文件在短时连续采样中修改时间未变化；这只能排除采样窗口内的写入。
- 生产数据库进程存在，常用兼容备份客户端仍未发现。

结论：尚不能授权任何生产写入、服务控制或部署操作。本次第三阶段只读审查和本地可复现性修复已完成；服务器 staging 写入仍须单独确认。

## 6. 第二阶段：固化协同协议

> 状态：已在本地完成文档固化，未修改 OpenClaw、systemd、cron 或服务器文件。

正式文档：

```text
docs/operations/OPENCLAW_CODEX_COLLABORATION.md
```

该文档应固化：

- GitHub 为正常代码协同来源，生产状态由只读巡检确认。
- Codex 与 OpenClaw 的分支命名、文件负责人、开工和交接格式。
- 服务器紧急热修的分支、测试、提交、推送和回收流程。
- OpenClaw 不自动覆盖 GitHub 明确 SHA，Codex 不直接覆盖 OpenClaw 生产工作区。
- 生产发布期间暂停相关 OpenClaw 自动开发或自动恢复任务的具体方式。
- 发布完成后恢复自动化前的健康检查。

如需修改 OpenClaw 配置、systemd 单元、timer 或 cron，必须单独列出目标、原值、修改值和恢复命令，并再次取得确认。

## 7. 第三阶段：staging 可复现性审查

目标发布源固定为 GitHub 上的：

```text
5f8bc18683c807dd0ef18b3b35735a7b4cffd016
```

### 7.1 当前容器方案限制

`fund-advisor/docker-compose.local.yml` 只定义 MySQL，不是完整应用部署方案。

后端 Dockerfile 已在本地修正为以 monorepo 根目录为构建上下文，并复制 `fund-analyzer/engine`；对应应用示例 Compose 也已改为根上下文。尚未在服务器创建镜像，仍需在独立环境完成构建证明。

前端 Dockerfile 已改为同时复制 `package.json` 和 `package-lock.json` 后执行 `npm ci`。本地锁文件为 v3、根依赖集合一致，生产构建通过；现有 Windows `node_modules` 的隐藏锁文件权限问题使本机 `npm ci --dry-run` 未能完成，干净环境仍需验证。

### 7.2 Linux 依赖复现检查

只读或在独立临时目录验证：

- 服务器 Python 是否为兼容的 3.12 版本。
- `fund-advisor/requirements.txt` 是否能完整解析和安装。
- `fund-analyzer` 是否有独立依赖声明，或需要生成统一 Linux 锁文件。
- 干净仓库中 `engine_bridge.py` 是否能定位同仓库 `fund-analyzer`。
- Alembic 配置是否只指向 staging 数据库。
- Node 与 npm 版本是否能从锁文件完成生产构建。

若必须复用生产虚拟环境、复制生产 site-packages 或绕过依赖冲突，停止。不得以生产环境“当前能运行”代替可复现性证明。

### 7.3 本次只读审查与本地修复结果

- 6 个测试入口已移除历史 `/root/.openclaw/workspace/fund-analyzer` 注入，统一由 `fund-analyzer/tests/conftest.py` 按仓库相对位置加载。
- 本地桥接探针可从 `fund-advisor` 工作目录导入 `fund-analyzer.engine` 和 `engine.analyzer`。
- 分析引擎 165 项、后端 5 项测试通过；前端生产构建转换 2102 个模块并通过，仅保留入口包体积提示。
- `docker-compose.yml.example`、`docker-compose.local.yml` 和 `docker-compose.staging.yml.example` 均已通过 YAML 静态解析。
- 新增 `fund-advisor/staging.env.example` 和 `fund-advisor/docker-compose.staging.yml.example`：独立数据库名/卷、调度与启动回补关闭、外部模型和邮件关闭、应用端口只绑定回环地址。
- `fund-analyzer` 仍缺少 Linux 锁文件或正式包元数据；这是当前最主要的 staging 可复现性阻塞，不能用 Windows 锁文件冒充 Linux 证明。

### 第三停止条件

出现任一情况不得部署 staging：

- 后端无法从明确依赖文件创建独立环境。
- `fund-analyzer` 无法在干净发布目录导入。
- 干净环境无法用锁文件完成 `npm ci` 或生产构建。
- staging 配置会读取生产数据库、生产 `.env`、上传文件或外发凭据。
- 需要修改 OpenClaw 生产工作区才能完成 staging。

## 8. 第四阶段：隔离 staging 方案

该阶段需要用户再次确认服务器写操作。

### 8.1 隔离要求

- 在 OpenClaw 生产工作区之外创建新的 staging/release 目录。
- 从 GitHub 检出明确 SHA，不复制本地脏工作区。
- 使用独立虚拟环境或经过审查的 staging 镜像。
- 使用独立 MySQL 8.0.43 合成数据库，不使用生产 MySQL，也不使用 NewAPI 的 MySQL 容器。
- staging 数据库容器使用独立 Compose 项目名、独立卷和随机本地凭据。
- 数据库、后端和前端只绑定 `127.0.0.1`。
- 调度器、启动净值回补、邮件外发和自动任务关闭。
- 不修改生产 systemd 单元、防火墙、公网域名和反向代理。
- staging 进程不能由 OpenClaw 的生产自动恢复规则接管。

如果 staging 已被严格证明不连接、不修改、不重启任何生产组件，可以先建立 staging；这不代表生产数据库备份门禁通过，也不授权生产切换。

### 8.2 推荐实施顺序

1. 确认无 OpenClaw 并发任务。
2. 创建服务器受控 staging 目录并记录权限。
3. 从 GitHub 获取 `5f8bc18`，核对完整 SHA 和干净工作区。
4. 建立独立 Python 环境并验证 `fund-analyzer` 导入。
5. 建立独立合成 MySQL，运行 Alembic 从零迁移。
6. 使用合成夹具运行两套 Python 测试。
7. 使用锁文件完成前端生产构建。
8. 选择未占用的回环端口启动 staging 后端和前端。
9. 验证健康接口、API、P0 四组正确性和三项服务器热修。
10. 通过 SSH 本地端口转发向用户提供访问地址。

### 8.3 staging 验收证据

- staging 目录、服务名、完整 SHA 和 Git 干净状态。
- Python、Node、数据库版本和依赖安装结果。
- 独立数据库名称、容器名和卷名；不展示密码。
- 调度器、邮件、生产数据访问关闭的证据。
- 两套 Python 测试、前端构建、健康接口和关键 API 结果。
- 回环监听和 SSH 隧道命令。
- staging 停止、重启和清理命令。
- 明确说明生产服务和 OpenClaw 工作区未修改。

## 9. 生产切换仍需单独确认

即使 staging 验收通过，也不得直接切生产。生产切换前仍必须：

- 修复或解释生产后端自动重启状态。
- 验证生产数据库兼容备份和恢复方案。
- 清理或安全迁移 OpenClaw 生产工作区的未提交热修。
- 确认 OpenClaw 自动任务在发布窗口中的暂停和恢复方式。
- 使用明确 GitHub SHA 和可回滚发布目录。
- 获得用户对生产服务、数据库和 OpenClaw 控制权变更的再次确认。

## 10. Luna 阶段汇报格式

### OpenClaw 只读调查后

- 本地和 GitHub SHA、剩余未提交文件。
- OpenClaw 进程、自动任务和项目控制范围。
- OpenClaw 与 systemd、Git 和生产工作区的关系。
- 是否发现并发写入或自动覆盖风险。
- 服务和数据库状态是否漂移。
- 是否建议进入协同协议与 staging 可复现性审查。
- 明确说明未修改本地或服务器。

### staging 可复现性审查后

- 选择完整仓库虚拟环境还是 staging 镜像，以及原因。
- Python、Node、`fund-analyzer` 和前端构建验证结果。
- staging 数据库隔离方案。
- 计划创建的服务器目录、服务、端口和回滚方式。
- 尚需用户确认的服务器写操作。

### staging 部署后

- 发布 SHA、目录、服务和回环端口。
- 测试和健康检查证据。
- 用户 SSH 隧道和本地访问地址。
- OpenClaw 与生产环境未被修改的证据。
- 是否具备用户验收条件。

## 11. 历史启动指令状态

以下任务已经完成，不得再次按旧提示重复调查或重写实现。当前启动入口统一使用 `05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md` 第 10 节。

```text
不要使用本节启动新任务；转读 05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md。
```

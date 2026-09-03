# Luna staging 发布包收口与隔离部署执行令

> 编写日期：2026-09-02
> 本地仓库：`E:\myfund11111`
> 当前阶段：本地 staging 可复现性修复已完成但尚未提交；生产后端临时稳定化已经完成，等待用户授权恢复本文件第二阶段
> 执行角色：用户在 Sol 授权，Sol 后台调度现有 Luna；Luna 是本阶段唯一写入者

## 1. 本轮目标

本轮必须按以下顺序推进，不能跨阶段：

1. 只读确认本地、GitHub、服务器和 OpenClaw 状态仍符合交接基线。
2. 只读复核本地 staging 修复、测试可移植性改动、运维文档和 5 个第四组文件的边界。
3. 向用户汇报拟生成的 Linux 依赖锁、干净验证方式、分支和提交拆分方案，并等待确认。
4. 获得确认后，在本地生成 Linux/Python 3.12 运行依赖锁，完成干净镜像构建和提交快照验证。
5. 只提交本执行令允许的文件，形成三个本地提交；5 个第四组文件继续保留为未提交改动。
6. 向用户汇报本地提交、完整 SHA 和验证证据，等待独立的 GitHub 推送确认。
7. 推送后再次只读核对服务器与 OpenClaw，向用户列出 staging 写入对象、端口、停止和回滚方式，并等待独立的服务器 staging 确认。
8. 获得服务器 staging 确认后，只在生产工作区之外部署隔离 staging，供用户通过 SSH 隧道验收。

本执行令默认停在 staging 用户验收，不切生产流量，不修改生产数据库，不迁移生产工作区。

## 2. 文档读取路由

首次执行本阶段、新建 Luna 任务、应用重启或上下文恢复不确定时，按顺序完整阅读：

1. `E:\myfund11111\AGENTS.md`
2. `E:\myfund11111\00_LUNA_START_HERE.md`
3. `E:\myfund11111\LUNA_HANDOFF.md`
4. `E:\myfund11111\docs\operations\CODEX_LUNA_ORCHESTRATION.md`
5. 本文件 `E:\myfund11111\04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md`

本地第二阶段只需额外读取：

- `docs/operations/OPENCLAW_CODEX_COLLABORATION.md` 第 2、3、4、6、9、11、12 节。
- `docs/operations/SYSTEM_ARCHITECTURE.md` 第 1.1、2、3、4、7 节。
- `docs/operations/RUNBOOK.md` 第 1、2、8 节。
- `ops/README.md` 的“当前服务器接入状态”和“正式发布前仍需补齐”部分。

首次进入服务器 staging 写阶段前，再完整阅读上述四份运维资料。`01`、`02`、`03`、`05`、`06` 和 `P0_ACCEPTANCE_REPORT.md` 属于历史证据；只有交接冲突、P0 验收变化或当前执行令明确引用证据时才读取对应章节，不再每轮全部重读。

若文档冲突，以 `AGENTS.md`、用户最新指令、本文件更严格的停止条件和生产安全边界为准。

## 3. 当前交接基线

以下状态来自 2026-09-02 最近一次核对，只用于漂移检测，不能代替 Luna 的实时检查：

- 本地分支：`codex/p0-server-readiness`。
- 本地 `HEAD` 和远程跟踪分支：`5f8bc18683c807dd0ef18b3b35735a7b4cffd016`。
- 暂存区为空；本轮 staging 修复和协同文档均未提交、未推送。
- 服务器生产工作区：`main` 的 `afc19e9b203141e8e604fc3f1b9f5dd438637a81` 加 3 个已知未提交热修。
- 服务器 3 个热修已经固化到 GitHub 的 `5f8bc18`，但生产工作区尚未迁移。
- OpenClaw 仍有运行进程；生产前后端由 systemd 管理并设置 `Restart=always`。
- 生产 MySQL 正在运行；兼容备份客户端和恢复证据尚未满足生产发布门禁。
- 已验证记录：分析引擎 165 项通过、后端 5 项通过、前端生产构建通过、3 份 Compose YAML 可解析。
- Windows 现有 `frontend\node_modules\.package-lock.json` 存在权限阻塞，不能以本机 `npm ci --dry-run` 作为干净安装证明。
- `fund-analyzer\requirements.txt` 只有直接依赖范围，没有 Linux/Python 3.12 的完整传递依赖锁；这是本地发布包的主要剩余阻塞。

## 4. 永久保护边界

### 4.1 5 个第四组文件

以下文件不属于本轮。不得编辑、格式化、清理、还原、暂存或提交：

- `fund-advisor/backend/services/calendar_service.py`
- `fund-advisor/backend/services/excel_parser.py`
- `fund-advisor/backend/services/nav_service.py`
- `fund-analyzer/tests/test_position.py`
- `fund-analyzer/tests/test_screener.py`

阶段开始和结束都要记录这 5 个文件的工作区差异清单与文件哈希；哈希发生变化时立即停止。

### 4.2 业务与生产边界

- 不重写已验收 P0，不开始 P1，不调整策略参数、风险阈值或模型选择规则。
- 不使用聊天中出现过的 GitHub Token，不在命令参数、输出、文档或提交中展示秘密。
- 不读取或复制生产 `.env`、真实持仓、数据库明细、上传文件、完整日志或凭据。
- 不覆盖 OpenClaw 生产工作区，不在服务器脏仓库执行拉取、切分支或覆盖式同步。
- 不修改 OpenClaw、cron、systemd、生产服务、生产数据库、防火墙、域名或反向代理。
- 不使用 `git add .`、`git add -A`、`git reset --hard`、`git clean`、强制推送或删除式同步。

## 5. 第一阶段：只读准入复核

本阶段只允许读取。不得创建分支、修改文件、生成锁、暂存、提交、推送、安装依赖、拉取镜像、创建容器、创建服务器目录或操作服务和数据库。

### 5.1 本地与 GitHub

执行前用中文解释每条命令的用途，然后核对：

```powershell
# 查看当前分支、远程跟踪关系和全部工作区差异。
git -C 'E:\myfund11111' status --short --branch

# 确认本地与远程跟踪分支仍位于交接 SHA。
git -C 'E:\myfund11111' rev-parse HEAD
git -C 'E:\myfund11111' rev-parse origin/codex/p0-server-readiness

# 分别列出已跟踪差异、未跟踪文件、暂存区和空白错误。
git -C 'E:\myfund11111' diff --name-status
git -C 'E:\myfund11111' ls-files --others --exclude-standard
git -C 'E:\myfund11111' diff --cached --name-status
git -C 'E:\myfund11111' diff --check
```

允许出现的本轮文件严格限于第 6 节白名单和 5 个第四组文件。出现任何来源不明文件时停止。

只读复核每个差异块，确认：

- 测试改动只移除 OpenClaw 绝对路径并使用仓库相对定位。
- Dockerfile、Compose 和环境模板只处理构建上下文、依赖复现、回环端口和 staging 隔离。
- 文档只固化协同、验收、发布和回滚边界。
- 没有策略参数、P0 业务实现、生产秘密或真实数据进入本轮白名单。

### 5.2 服务器与 OpenClaw 最小漂移核对

使用已有 `ops/.env` 和 SSH 安全参数，只读核对：

- 服务器仍为 `afc19e9` 加严格相同的 3 个热修文件。
- OpenClaw 没有正在修改本项目文件、拉取代码或重启目标服务。
- 后端、前端、MySQL 和 systemd 重启策略没有新异常。
- 没有新自动拉取、文件监控、定时部署或覆盖机制。
- 预定 staging 回环端口尚未被占用；只记录端口占用结论，不输出私密地址。

本阶段不得读取配置值或完整日志，也不得以只读巡检名义创建服务器备份。

### 5.3 第一阶段汇报

向用户汇报并等待确认：

- 本地分支、完整 SHA、远程 SHA、暂存区和差异文件集合。
- 5 个第四组文件的保护状态。
- 本轮白名单文件按“测试可移植性、staging 构建、文档运维”分组。
- Linux 依赖锁拟采用的工具、固定工具版本、Python 3.12 Linux 环境和输出文件名。
- 干净后端镜像、前端 `npm ci` 镜像和提交快照测试方案。
- 拟创建分支、三个提交及推送目标。
- 服务器和 OpenClaw 是否发生漂移。
- 明确说明尚未修改、暂存、提交、推送或操作服务器。

未获得用户对第二阶段的明确确认前，必须停止。

## 6. 第二阶段：本地发布包收口

只有用户明确允许创建分支、生成锁、拉取必要的公开基础镜像、在本地一次性 Linux/Docker 环境安装依赖、清理本阶段自行创建的临时资源、暂存和提交后，才执行本阶段。推送 GitHub 不包含在本阶段默认授权内，必须在本地提交和验收完成后另行确认；只有用户的原始授权逐字包含推送时才可合并执行。

### 6.1 允许文件白名单

现有允许文件：

- `.gitignore`
- `00_LUNA_START_HERE.md`
- `LUNA_HANDOFF.md`
- `02_LUNA_SERVER_RELEASE_READINESS.md`
- `03_LUNA_OPENCLAW_COLLABORATION.md`
- `04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md`
- `05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md`
- `06_LUNA_PRODUCTION_STABILIZATION.md`
- `docs/operations/CODEX_LUNA_ORCHESTRATION.md`
- `docs/operations/OPENCLAW_CODEX_COLLABORATION.md`
- `docs/operations/RUNBOOK.md`
- `docs/operations/SYSTEM_ARCHITECTURE.md`
- `ops/README.md`
- `fund-advisor/Dockerfile`
- `fund-advisor/docker-compose.yml.example`
- `fund-advisor/docker-compose.staging.yml.example`
- `fund-advisor/staging.env.example`
- `fund-advisor/frontend/Dockerfile`
- `fund-analyzer/tests/conftest.py`
- `fund-analyzer/tests/fixtures/__init__.py`
- `fund-analyzer/tests/test_analyzer.py`
- `fund-analyzer/tests/test_llm_client.py`
- `fund-analyzer/tests/test_portfolio_quant.py`
- `fund-analyzer/tests/test_prompts.py`
- `fund-analyzer/tests/test_quant.py`

允许新增一个 Linux 运行依赖锁文件。首选路径：

```text
fund-advisor/requirements-linux.lock
```

若审查证明必须使用其他文件名或增加输入文件，先汇报原因并等待确认，不得自行扩大白名单。

### 6.2 分支与工作区保护

拟创建分支：

```text
codex/p0-staging-readiness
```

创建前确认当前 `HEAD=5f8bc18683c807dd0ef18b3b35735a7b4cffd016`、暂存区为空，并记录 5 个第四组文件哈希。创建分支后立刻再次核对它们的哈希和差异。

不得用 stash、checkout、restore、clean 或 reset 临时隐藏第四组改动。只通过逐文件白名单暂存隔离本轮提交。

### 6.3 Linux 运行依赖锁

在一次性、非生产、Python 3.12 Linux 环境中，根据以下两个输入共同解析运行依赖：

- `fund-advisor/requirements.txt`
- `fund-analyzer/requirements.txt`

要求：

- 使用固定版本的依赖解析工具，并在锁文件头或交接中记录版本和生成命令。
- 输出所有传递依赖的精确版本；优先生成哈希并在镜像安装时启用哈希校验。
- 不使用 Windows `pip freeze`，不复制生产虚拟环境或生产 `site-packages`。
- 不把测试工具、开发工具或本机绝对路径混入运行锁。
- 用 Python 3.12 Linux 环境验证锁文件可从空环境安装，并能导入 FastAPI、SQLAlchemy、pandas、NumPy；再通过应用桥接入口导入 `engine.analyzer` 和后端应用入口。
- 将 `fund-advisor/Dockerfile` 改为使用该锁文件；不得继续只靠范围依赖直接解析生产镜像。

若解析出现冲突、需要修改业务依赖范围或只能通过忽略哈希继续，立即停止并报告，不猜测升级版本。

### 6.4 干净构建与验证

不得把现有 Windows `node_modules` 作为验收环境。使用干净构建上下文完成：

1. 后端镜像从 monorepo 根目录构建，锁文件安装成功，`fund-analyzer` 导入成功。
2. 前端镜像通过 `package-lock.json` 执行 `npm ci` 并完成生产构建。
3. staging Compose 使用虚构密码做配置展开和静态校验，不启动生产服务、不读取生产 `.env`。
4. 两套 Python 测试使用 `-p no:cacheprovider`，并关闭字节码写入。
5. 运行敏感信息和历史绝对路径检查；不得输出命中的秘密正文。

首次验证可以在当前工作区进行，但不能作为最终提交证据。提交完成后必须从新提交 SHA 创建 `%TEMP%` 下的 detached 临时 worktree，在该干净快照中重新执行两套 Python 测试、后端镜像构建、前端镜像构建和 Compose 校验。

临时 worktree 和一次性容器只能在记录测试结果后清理；不得删除共享镜像、卷、生产资源或现有 `node_modules`。清理前后都要确认仓库工作区和第四组文件没有变化。

### 6.5 提交拆分

只使用逐文件 `git add -- <明确路径>`，建议拆为三个提交：

1. `test(staging): 移除分析引擎测试的服务器路径依赖`
   - `fund-analyzer/tests/conftest.py`
   - `fund-analyzer/tests/fixtures/__init__.py`
   - 5 个白名单测试文件
2. `build(staging): 固化隔离环境与 Linux 依赖`
   - `.gitignore`
   - 后端和前端 Dockerfile
   - 两份应用 Compose 模板、staging 环境模板
   - Linux 运行依赖锁
3. `docs(operations): 固化模型调度、OpenClaw 协同与 staging 执行令`
   - 交接入口、`02`、`03`、`04`、`05`、`06`
   - Sol/Luna 调度规范、OpenClaw 协同规范、架构、运维手册和 `ops/README.md`

每次暂存后执行：

```powershell
# 只检查本次已暂存文件、空白错误和差异统计。
git -C 'E:\myfund11111' diff --cached --name-status
git -C 'E:\myfund11111' diff --cached --check
git -C 'E:\myfund11111' diff --cached --stat
```

若暂存区出现白名单外文件、任何第四组文件或无法解释的差异块，立即停止并取消该次暂存，不创建提交。

### 6.6 推送门禁与汇报

只有以下条件全部满足，并且用户在 Sol 中另行明确确认推送后，才可推送 `codex/p0-staging-readiness`：

- 三个提交边界清楚，提交快照不包含 5 个第四组文件。
- detached 干净快照中的两套 Python 测试、后端镜像、前端镜像和 Compose 校验全部通过。
- 敏感信息与服务器绝对路径检查通过。
- 当前工作区仍只剩 5 个第四组文件，内容哈希与阶段开始一致。
- 未修改服务器、OpenClaw、systemd、cron、生产服务或数据库。

条件满足但尚未获得推送确认时，只汇报本地分支、三个提交和最终完整 SHA，然后停止。不得把“恢复第二阶段”“继续”或本地提交授权解释为推送授权。

推送后记录完整 SHA，并向用户汇报：

- 分支、三个提交和最终完整 SHA。
- 每组实际文件清单。
- Linux 锁生成环境、工具版本和安装证明。
- 干净快照测试与构建结果。
- 仍保留的 5 个第四组文件及哈希一致结论。
- GitHub 推送状态。
- 明确说明尚未部署任何服务器环境。

## 7. 第三阶段：服务器 staging 写入前复核

第二阶段完成不自动授权服务器写入。先只读重新核对：

- GitHub 目标分支确实包含最终完整 SHA。
- 服务器生产 SHA、3 个脏热修、OpenClaw、systemd 和 MySQL 状态未漂移。
- 生产工作区之外的候选 staging 父目录真实存在或其父目录可受控创建。
- 计划端口仅监听回环且未占用；默认候选为后端 `18200`、前端 `18201`，实际以只读检查为准。
- Docker/Compose 版本、可用空间、镜像架构和卷命名不会与生产冲突。
- staging 不会读取生产 `.env`、数据库、上传目录、日志、LLM Key 或 SMTP 凭据。

然后向用户逐项说明并等待服务器 staging 确认：

- 将创建的服务器 staging 目录。
- 将检出的完整 GitHub SHA。
- 将创建的 Compose 项目、镜像、容器、独立数据库和卷。
- 将创建的 `staging.env` 路径与权限；只说明字段来源，不输出值。
- 回环端口和 SSH 隧道访问方式。
- Alembic 从零迁移、合成夹具和健康检查范围。
- 停止命令、保留数据的回滚命令和需要再次确认的彻底清理命令。
- 生产工作区、OpenClaw、systemd、cron 和生产数据库明确不修改。

未获得第二次明确确认前，不得创建服务器目录、拉取代码、写配置、拉取镜像、创建容器、卷或数据库。

## 8. 第四阶段：隔离 staging 部署

只有获得服务器 staging 确认后才执行。要求：

1. 在 OpenClaw 生产工作区之外创建权限受控的新目录。
2. 从 GitHub 检出第二阶段最终完整 SHA，确认工作区干净且 `HEAD` 完全相等。
3. 创建只属于 staging 的运行配置，使用随机本地密码，不使用生产凭据。
4. 使用独立 Compose 项目名、MySQL 8.0.43 合成数据库、独立命名卷和回环端口。
5. 保持调度器、启动净值回补、邮件、外部模型和自动任务关闭。
6. 从零运行 staging Alembic 迁移，只针对 staging 数据库。
7. 使用虚构夹具验收后端健康、前端首页、关键 API、P0 四组正确性和 3 项热修。
8. 通过 SSH 隧道向用户提供本地访问地址，不开放公网入口。
9. 不创建或修改生产 systemd 单元；staging Compose 的 `restart` 保持关闭。

### 8.1 回滚与停止

- 验收失败时先停止 staging Compose，保留目录、配置和独立卷供审查。
- 停止 staging 不得停止、重启或修改生产服务。
- 删除 staging 目录、镜像、容器或数据库卷属于单独的清理动作；列出精确对象并再次确认后才能执行。
- 任何健康检查失败、生产状态漂移、OpenClaw 并发写入或秘密边界异常都要立即停止扩大变更。

### 8.2 staging 汇报

- 完整发布 SHA、服务器 staging 目录和 Git 干净状态。
- Compose 项目、容器、数据库、卷和回环端口；不展示密码。
- Python、Node、npm、MySQL 和镜像标识。
- Alembic 从零迁移、测试、构建、健康和关键 API 结果。
- 调度、回补、邮件、外部模型和生产数据访问关闭证据。
- 用户 SSH 隧道命令和本地访问地址。
- 停止、再次启动和保留数据回滚方式。
- 明确说明生产工作区、OpenClaw、systemd、cron、生产服务和生产数据库均未修改。

## 9. 立即停止条件

出现任一情况立即停止并报告：

- 本地、GitHub 或服务器 SHA、分支、脏文件与基线不一致且不能解释。
- 5 个第四组文件内容或哈希变化，或进入暂存区/提交。
- OpenClaw 或另一执行端正在修改同一文件，或自动覆盖/重启触发条件不明。
- Linux 锁无法从两个输入依赖在 Python 3.12 Linux 环境干净生成和安装。
- 前端不能在干净环境通过 `npm ci` 和生产构建。
- 提交快照测试或镜像构建失败。
- staging 可能连接生产数据库、使用生产凭据、读取生产文件或暴露公网端口。
- 需要覆盖服务器脏工作区、复用生产虚拟环境或修改生产 systemd 才能继续。
- 需要展示 Token、密码、私钥、真实持仓或完整日志才能继续。

`05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md` 的只读诊断和 `06_LUNA_PRODUCTION_STABILIZATION.md` 的生产临时稳定均已完成。当前仍未获得恢复本文件第二阶段的确认；确认前不得创建分支、生成锁、暂存、提交、推送或创建本地临时环境。

## 10. Sol 获得确认后发送给 Luna 的恢复指令

> 用户只需在 Sol 中确认。Sol 按 `docs/operations/CODEX_LUNA_ORCHESTRATION.md` 后台发送本节，不要求用户手工复制或切换窗口。

```text
阶段与目标：在 E:\myfund11111 执行 `04` 第二阶段，只完成本地发布包收口。
依据：按 `00_LUNA_START_HERE.md` 和 `04` 第二节读取核心文档与指定章节，严格执行 `04`。
已授权：创建 `codex/p0-staging-readiness`；拉取必要公开基础镜像；在一次性 Python 3.12
Linux/Docker 环境安装依赖并生成 Linux 锁；运行 `04` 规定的完整测试、构建、Compose、
敏感信息和 detached 快照验证；逐文件暂存并创建三个本地提交；清理本阶段自行创建的
临时 worktree 和一次性容器。
禁止：推送、服务器写入、staging 部署、服务或进程操作、数据库操作、OpenClaw/cron/
systemd/tat_agent 修改、策略参数和 P0 重写；不得处理 5 个第四组文件或共享镜像/卷。
验收：执行 `04` 第 6.3 至 6.5 节全部门禁，提交后仍保持白名单和保护文件哈希一致。
停止与回滚：任何漂移、依赖冲突、测试/构建失败或白名单外需求都停止；不擅自扩大范围。
基线增量：`04` 第一阶段和 `06` 已完成；当前预期为 25 个候选加 5 个第四组文件。动作前
实时复核分支、SHA、本地/GitHub、服务器 3 个热修、OpenClaw 和旧健康后端。完成后按
精简结果格式汇报并等待独立的 GitHub 推送确认。
```

事实补记：本机 Docker Hub 的 auth.docker.io 与 registry-1.docker.io 出站连通性不可达；本机镜像门禁改由明确 GitHub SHA 在生产工作区之外的服务器 staging 中完成干净构建。本机网络阻塞不构成生产发布验收。
Staging-only 基线例外：detached 快照中的 test_position.py::test_action_amount_with_total_mv 与 test_screener.py::test_base_weights_loaded 属于既有 RFC-021/RFC-018 语义与旧断言不一致，允许在 staging 中登记为已知失败；这不构成全绿验收，生产发布仍被阻塞。

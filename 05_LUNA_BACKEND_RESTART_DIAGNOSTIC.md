# Luna 生产后端自动重启只读诊断执行令

> 编写日期：2026-09-02
> 本地仓库：`E:\myfund11111`
> 当前状态：只读诊断已于 2026-09-03 完成；后续入口为 `06_LUNA_PRODUCTION_STABILIZATION.md`
> 执行角色：本文件只保留诊断方法与历史证据，不授权任何修复或重启

## 1. 任务目标

本轮只回答三个问题：

1. `fund-advisor-backend.service` 为什么反复退出并被 systemd 拉起。
2. systemd 实际运行目录、代码来源、Python 环境和生产 Git 工作区之间是什么关系。
3. 后续最小修复应属于代码、依赖、配置、systemd、数据库连接还是运行资源问题。

完成只读诊断后，向用户提供脱敏证据、根因判断、最小修复建议和回滚方式，然后等待确认。不得直接修复。

## 2. 必须完整阅读

开始前按顺序完整阅读：

1. `E:\myfund11111\AGENTS.md`
2. `E:\myfund11111\00_LUNA_START_HERE.md`
3. `E:\myfund11111\LUNA_HANDOFF.md`
4. `E:\myfund11111\02_LUNA_SERVER_RELEASE_READINESS.md`
5. `E:\myfund11111\03_LUNA_OPENCLAW_COLLABORATION.md`
6. `E:\myfund11111\04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md`
7. `E:\myfund11111\docs\operations\SYSTEM_ARCHITECTURE.md`
8. `E:\myfund11111\docs\operations\RUNBOOK.md`
9. `E:\myfund11111\docs\operations\OPENCLAW_CODEX_COLLABORATION.md`
10. `E:\myfund11111\ops\README.md`
11. 本文件 `E:\myfund11111\05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md`

若文档冲突，以 `AGENTS.md`、用户最新指令、本文件的只读边界和更严格的生产安全规则为准。

## 3. 当前事件基线

2026-09-02 最近一次只读核对得到：

- 本地与 GitHub 分支 `codex/p0-server-readiness` 均为 `5f8bc18683c807dd0ef18b3b35735a7b4cffd016`。
- 本地暂存区为空，工作区仍是 22 个 staging 候选文件加 5 个第四组文件；本文件加入后应为 23 个候选文件加 5 个第四组文件。
- 服务器生产 Git 工作区仍为 `main` 的 `afc19e9b203141e8e604fc3f1b9f5dd438637a81`，只有 3 个已知热修文件未提交。
- 服务器 Git 工作区登记路径与后端 systemd 的 `WorkingDirectory` 不是同一路径；必须确认两者是独立副本、符号链接还是历史运行目录。
- 后端服务配置 `Restart=always`，两次间隔采样分别出现 `active/running` 与 `activating/auto-restart`。
- 后端 `Result=exit-code`，累计重启计数为 `1767`；该数值是快照，Luna 必须实时复核。
- 前端服务为 `active/running`、累计重启为 0，但也配置 `Restart=always`。
- OpenClaw 进程和用户级监控任务仍存在；未发现常见文件监控器、活动 Git 进程或匹配的 systemd timer。
- 生产 `mysqld` 正在运行；`mysqldump`、`mariadb-dump`、`mysqlpump` 和 `xtrabackup` 均未发现。
- staging 候选端口 `18200`、`18201` 当时空闲；这与生产后端重启原因无直接结论。

以上仅用于检测漂移，不能当作永久事实。

## 4. 全程禁止事项

- 不执行 `systemctl start`、`stop`、`restart`、`reload`、`daemon-reload`、`reset-failed` 或 `enable/disable`。
- 不终止、暂停或向 OpenClaw、uvicorn、systemd、MySQL、Docker 进程发送信号。
- 不编辑、复制覆盖、移动或删除服务器代码、unit、环境文件、日志、数据库或运行目录。
- 不创建备份、临时服务器文件、目录、容器、镜像、卷、虚拟环境或软件包安装记录。
- 不读取或输出 `.env` 的值、数据库连接串、Token、Cookie、密码、私钥、真实持仓或完整日志。
- 不在生产工作区执行 `git pull`、`switch`、`checkout`、`reset`、`clean`、`stash` 或任何写 Git 状态的命令。
- 不修改本地文件，不创建分支，不生成锁，不暂存、提交或推送。
- 不处理 5 个第四组文件，不调整策略参数，不重写 P0，不部署 staging，不切生产流量。

## 5. 第一阶段：本地与 GitHub 门禁复核

先用中文解释每条命令用途，再只读确认：

```powershell
# 核对本地分支、远程跟踪关系和全部差异。
git -C 'E:\myfund11111' status --short --branch

# 核对本地、远程跟踪和 GitHub 实际分支 SHA。
git -C 'E:\myfund11111' rev-parse HEAD
git -C 'E:\myfund11111' rev-parse origin/codex/p0-server-readiness
git -C 'E:\myfund11111' ls-remote --heads origin codex/p0-server-readiness

# 确认暂存区为空并检查现有差异格式。
git -C 'E:\myfund11111' diff --cached --name-status
git -C 'E:\myfund11111' diff --check
```

预期差异严格等于 `04` 白名单加本文件和 5 个第四组文件。任何新代码差异、暂存内容或 SHA 漂移都要停止。

## 6. 第二阶段：生产后端只读诊断

使用 `E:\myfund11111\ops\.env` 中已有 SSH 配置和已核对主机指纹。只通过读取命令采集证据，不输出连接信息。

### 6.1 确认重启循环

在 15 至 30 秒内进行 3 至 5 次间隔采样，记录但不干预：

- `ActiveState`、`SubState`、`Result`、`MainPID`、`ExecMainCode`、`ExecMainStatus`。
- `NRestarts` 是否递增，PID 是否反复变化。
- 后端本地健康接口是否在采样窗口内交替成功和失败。
- 生产端口是否存在多个监听者；只汇报端口和进程名称，不输出网络地址。

如果服务恢复稳定，也必须继续查明最近一次退出原因，不能把短时 `active/running` 当作问题消失。

### 6.2 核对 systemd 单元边界

只读检查 `fund-advisor-backend.service`：

- unit 文件路径、`WorkingDirectory`、`User`、`Group`、`Restart` 和重启等待时间。
- `ExecStart` 使用的 Python/uvicorn 路径、模块入口和参数；不得输出内嵌秘密。
- `EnvironmentFile` 只记录文件路径、是否存在、属主和权限，不读取文件值。
- 若 unit 内存在内嵌 `Environment=`，只列出变量名并标记风险，不输出值。
- 依赖的 target、socket、mount 或其他 unit 是否失败。

不得把完整 unit 原文直接贴到聊天。汇报时只保留上述允许字段。

### 6.3 核对运行目录与代码身份

分别确认生产 Git 工作区和 systemd `WorkingDirectory`：

- `readlink -f` 解析后的真实目录。
- 是否为 Git 工作区、当前分支、完整 SHA、脏文件名。
- 两个目录是否是同一 inode、符号链接、嵌套目录或独立代码副本。
- `backend.main`、`engine_bridge.py`、`fund-analyzer` 目录和 3 个热修文件实际来自哪一个目录。
- 只比较文件大小、修改时间和哈希；不把完整源码或补丁输出到聊天。

若 systemd 运行目录不是已知 Git 工作区，必须把它视为独立生产事实来源，禁止猜测切换路径。

### 6.4 核对 Python 与导入链

使用 `ExecStart` 指向的同一个 Python，只执行不会写入文件、不会启动应用的查询：

- 通过包元数据查询 Python、uvicorn、FastAPI、SQLAlchemy、pydantic、pandas、NumPy 和 PyMySQL 版本，避免为查版本导入应用。
- Python 可执行文件真实路径、`sys.prefix` 和是否属于虚拟环境。
- 使用模块定位、文件存在性和 AST 解析确认 `backend.main`、`engine_bridge`、`engine.analyzer` 的来源与语法，不执行 `backend.main`、uvicorn 或应用启动入口。
- 只有日志已经明确指向第三方基础包导入失败时，才可在关闭字节码写入后单独导入该基础包；不得导入会启动调度、数据库、邮件或外部模型的应用模块。
- 定位或解析失败时只汇报异常类型、模块、文件和行号，不输出环境变量或业务数据。
- 检查 `PYTHONDONTWRITEBYTECODE`；若未设置，诊断命令显式关闭字节码写入。

不得执行 `pip install`、`pip freeze` 全量输出、依赖升级、复制生产 `site-packages`、运行 uvicorn 或触发 FastAPI lifespan。

### 6.5 读取最小化日志证据

只读取最近 10 至 15 分钟或最多 120 行的后端 unit 日志。内部分析可以查看必要堆栈，但对用户只汇报：

- 第一条和最后一条失败时间。
- 重复失败次数和最常见的异常类型。
- 最末端异常的模块、文件、函数和行号。
- 是否属于导入、配置、端口、数据库、权限、资源或应用启动逻辑。

汇报前必须删除或遮蔽地址、连接串、Token、Cookie、密码、邮箱、真实基金代码、持仓和请求正文。不得复制整段日志。

### 6.6 外部依赖和资源检查

只读确认：

- 磁盘、内存、文件描述符和进程限制是否耗尽。
- 生产后端端口是否冲突。
- MySQL 进程和本地端口是否存在；不连接数据库、不读取凭据、不执行 SQL。
- 后端依赖的本地目录和配置文件是否存在、权限是否允许运行用户读取。
- OpenClaw、cron 或其他守护进程是否同时启动、覆盖或替换后端。

数据库是否可认证、表结构和数据内容不属于本轮；若日志指向数据库认证失败，只记录分类并停止。

## 7. 根因分类与停止条件

诊断只能把问题归入以下一类或多类，不得直接修复：

1. systemd 运行目录或启动命令漂移。
2. Python 虚拟环境或运行依赖缺失/冲突。
3. `fund-analyzer` 桥接或模块导入失败。
4. 环境文件缺失、权限错误或必填键缺失。
5. 端口冲突或重复进程。
6. MySQL/外部依赖不可达或认证失败。
7. 应用 lifespan、调度器或启动任务异常。
8. 系统资源、权限或文件系统问题。
9. OpenClaw、cron 或其他自动恢复链并发干预。
10. 证据不足或存在多个独立故障。

出现以下情况立即停止：

- 只读检查需要展示秘密、完整日志或真实业务数据才能继续。
- 发现 OpenClaw 正在写入目标文件或主动替换后端进程。
- 生产 Git 工作区或 3 个热修文件发生新漂移。
- 数据库、前端或其他生产组件也开始异常。
- 诊断命令可能触发应用启动、写缓存、连接外部模型或执行调度任务。
- 无法确认某条命令是否只读。

## 8. Luna 汇报格式

完成只读诊断后必须汇报：

- 本地、GitHub、服务器分支和完整 SHA，是否发生漂移。
- 5 个第四组文件是否仍受保护，暂存区是否为空。
- 后端采样次数、状态变化、重启计数变化和健康接口结果。
- systemd 工作目录与服务器 Git 工作区的关系。
- 实际 Python/uvicorn 路径及核心依赖版本。
- 最小化日志结论和根因分类，附证据强度：确认、很可能、可能或未知。
- 是否有 OpenClaw、cron、端口、数据库或资源并发因素。
- 一个首选最小修复方案和一个备选方案；分别列出拟修改对象、风险、验证和回滚。
- 明确说明未修改文件、未重启服务、未操作数据库、未部署 staging。

汇报后等待用户确认。即使根因明确，也不得执行修复。

## 9. 后续决策门

- 若根因属于本地代码或依赖，应回到本地分支，通过 GitHub 明确 SHA 修复和验证，不在服务器手改。
- 若根因属于 systemd、运行目录或环境文件，应先列出服务器备份、修改、验证和恢复命令，单独获得确认。
- 若根因属于数据库，应单独进入数据库只读诊断；没有备份工具时禁止重启或写入数据库。
- 若 OpenClaw 正在并发控制，应先与用户确认维护窗口和暂停/恢复方式。
- 只有生产后端稳定、根因和恢复路径清楚后，才由用户决定是否恢复 `04` 第二阶段。

## 10. 历史启动指令（诊断已完成，不再发送）

以下指令仅保留为审计记录。当前应使用 `06_LUNA_PRODUCTION_STABILIZATION.md` 第 11 节的启动指令。

```text
在 E:\myfund11111 执行生产后端自动重启的只读诊断。
先完整阅读 AGENTS.md、00_LUNA_START_HERE.md、LUNA_HANDOFF.md、
02_LUNA_SERVER_RELEASE_READINESS.md、03_LUNA_OPENCLAW_COLLABORATION.md、
04_LUNA_STAGING_PACKAGE_AND_DEPLOYMENT.md、docs/operations/SYSTEM_ARCHITECTURE.md、
docs/operations/RUNBOOK.md、docs/operations/OPENCLAW_CODEX_COLLABORATION.md、
ops/README.md 和 05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md。

严格按 05_LUNA_BACKEND_RESTART_DIAGNOSTIC.md 执行。本轮只允许只读核对本地、
GitHub、服务器、OpenClaw 和 fund-advisor-backend.service，确认重启循环、systemd
运行目录与生产 Git 工作区关系、实际 Python/uvicorn 与导入链、最近最小化错误、
端口、MySQL 进程和资源状态。只汇报脱敏结论、根因分类、最小修复与回滚方案，
然后等待确认。

不要修改本地或服务器文件，不要创建分支、锁文件、暂存、提交、推送、备份、
临时目录、容器或虚拟环境；不要安装依赖，不要运行任何 systemctl 写操作，不要
终止或重启进程，不要读取或输出环境值、数据库内容、真实持仓或完整日志。不要处理
5 个第四组文件，不调整策略参数，不重写 P0，不部署 staging，不切生产流量。
```

## 11. 诊断完成交接

2026-09-03 只读诊断确认：

- 本地、跟踪分支和 GitHub 分支仍为 `5f8bc18683c807dd0ef18b3b35735a7b4cffd016`，暂存区为空，5 个第四组文件未处理。
- 服务器生产工作区仍为 `afc19e9b203141e8e604fc3f1b9f5dd438637a81` 加 3 个已知未提交热修。
- systemd `WorkingDirectory` 是生产 Git 工作区内的 `fund-advisor` 子目录，不是独立副本。
- systemd 的 uvicorn/虚拟环境来自另一套历史路径，运行目录与解释器目录存在漂移。
- 后端 unit 每 10 秒自动重试；最近快照累计重启 6539 次。
- 最小化日志确认直接根因为 8200 已被占用，错误分类为“端口冲突或重复进程”。
- 8200 由旧 uvicorn PID 4070714 占用；该进程父进程为 1，位于 backend unit 控制组之外，`/health` 正常。
- 服务器缺少 `backend/engine_bridge.py`，模块定位无法解析 `backend.engine_bridge` 和 `engine.analyzer`，属于端口问题解决后可能暴露的第二阻塞。
- 前端服务稳定；OpenClaw 进程和一个用户级监控 cron 存在，但没有证据证明其直接启动旧 uvicorn。
- 磁盘和内存没有耗尽证据；MySQL 进程存在，本次未连接数据库。

诊断已经完成，不应再次执行广泛调查。下一步按 `06` 先做最小漂移复核，再由用户逐项授权生产稳定化。

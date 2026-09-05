# Luna 持仓写入、导入与基金信息补全正确性修复执行令

> 编写日期：2026-09-04
> 本地仓库：`E:\myfund11111`
> 指挥角色：当前 Sol 任务
> 唯一执行角色：现有 Luna 任务
> 当前阶段：本地实现与回归测试；完成后停止，等待提交、推送和 staging 更新的独立授权

## 1. 用户最新授权

用户已明确授权本次正确性修复，并允许修改此前第五组中的以下三个服务文件：

- `fund-advisor/backend/services/calendar_service.py`
- `fund-advisor/backend/services/excel_parser.py`
- `fund-advisor/backend/services/nav_service.py`

以下两个既有改动仍受保护，不得编辑、格式化、还原、暂存或提交：

- `fund-analyzer/tests/test_position.py`
- `fund-analyzer/tests/test_screener.py`

用户要求先在独立 staging 数据库验证，仍不切生产。根据长期协同规范，本阶段只授权本地分支、代码修改和测试；暂存、提交、推送、服务器 staging 更新、数据库迁移执行和容器替换均不包含在本阶段，完成本地验证后必须停止并汇报。

## 2. 必须阅读与实时基线

开始前完整阅读：

1. `AGENTS.md`
2. `00_LUNA_START_HERE.md` 顶部的 2026-09-04 当前权威增量
3. `LUNA_HANDOFF.md` 顶部的 2026-09-04 当前权威交接
4. `docs/operations/CODEX_LUNA_ORCHESTRATION.md`
5. 本文件
6. `fund-advisor/PROJECT.md` 的数据模型、Holdings、Imports、NAV 和服务职责章节
7. `fund-advisor/docs/RFC-011-holding-change-ops.md`

随后只读复核以下实时状态：

- 当前分支预期为 `codex/p0-staging-readiness`。
- 当前 `HEAD`、跟踪分支和 GitHub 目标分支预期为 `6a7744577d76e8ea40fbef7d83700a2c202b815f`。
- 暂存区应为空。
- 工作区预期包含原有五个文件差异，以及 Sol 新增或更新的本执行令和交接入口文档。
- 三个已授权服务文件原有差异仅为 `from __future__ import annotations`；必须保留，可在其上继续修复。
- 两个仍受保护的分析引擎测试文件必须记录开始哈希，阶段结束时复核完全一致。

若出现来源不明的代码差异、暂存内容、不同 HEAD，或另一个执行端正在写入，立即停止并汇报，不创建分支、不修改文件。

## 3. 已确认的问题，不再重复广泛调查

### 3.1 基金信息和零份额

- 快捷导入只查本地 `funds` 和 `fund_nav_history`，不会按需请求名称与最新净值。
- 未命中时创建 `基金{代码}` 占位名称并把份额写成零。
- NAV 刷新只更新 `funds` 的净值字段，不补基金名称。
- 后续市值重算不能把零份额按原始金额补回，反而可能把已录入市值算成零。
- `fund-analyzer/engine/market_data.py` 已有公开基金详情能力；服务器 staging 已用公开示例确认名称源和净值源均可访问。

### 3.2 三套持仓写入路径分裂

- 手工新增、快捷导入、Excel/ZIP 导入使用不同服务逻辑和不同虚构账户键。
- 快捷导入硬编码支付宝，手工新增要求名称与份额，行为和语义不一致。
- `funds.fund_name` 与 `fund_holdings.fund_name` 双写，响应优先读取持仓副本，容易长期漂移。
- 快捷导入和手工新增不进入导入历史或统一变动账本。

### 3.3 Excel/ZIP 合并边界错误

- 单个 Excel 导入会把数据库中所有未出现在该文件的活动持仓清仓，没有限定为同一导入来源。
- ZIP 对每个 Excel 分别合并和清仓，后一个文件可能清掉前一个文件的数据。
- 顶层 Excel 可能同时被 `glob` 和 `rglob` 收集两次。
- 有解析错误的部分文件仍可能触发清仓。
- 文档宣称支持多 Sheet 和 `.xls`，当前实现只读活动 Sheet，且 `openpyxl` 不支持旧 `.xls`。

### 3.4 变动账本与收益链路错误

- 手工加减仓使用 `import_id=0`；快照和收益日历通过 `import_records` 联表，因此读不到这些变动。
- 手工减仓把 `shares_delta` 记录为正数，而资金流约定负数代表卖出。
- 手工创建、快捷导入和删除没有统一记录业务日期、来源和变动事件。
- 因此页面操作成功并不代表组合净值、净资金流、收益日历和历史重建正确。

### 3.5 事务、校验和上传安全

- 快捷导入逐条提交，异常后缺少明确回滚；批次可能部分写入且后续记录继续使用失败 Session。
- `SimpleImportRecord.share_date = date.today()` 在模块加载时求值，不是每次请求求值。
- 手工新增缺少与快捷导入一致的基金代码、金额、平台和重复身份校验。
- 上传文件名直接参与服务器路径，文件整体读入内存，没有文件大小限制。
- ZIP 使用 `extractall`，没有路径穿越、成员数、单成员大小和解压总量限制。
- Nginx 没有明确上传大小限制，前后端限制也未统一。
- 当前后端测试不覆盖上述路径。

## 4. 本次必须满足的业务不变量

实现方式可以在不扩大架构的前提下调整，但以下结果不可改变：

1. `Fund` 是基金名称和最新净值的规范来源；持仓响应不得因副本滞后显示占位名称。
2. 未知基金快捷录入时必须按需获取公开基金名称和最新净值。
3. 获取失败时返回明确、可重试的逐条错误；不得创建伪正常的零份额活动持仓。
4. 对历史遗留的“占位名称 + 零份额 + 正市值”记录，只有在成功获取净值后才可用原市值反算份额；不得先把原市值覆盖成零。
5. 当前市值不是成本。快捷导入没有成本信息时，`cost_nav` 保持未知，不得用最新净值伪造零盈亏。
6. 手工新增、快捷导入、Excel/ZIP、新增、加仓、减仓、删除/清仓都必须通过统一的身份校验、事务边界和变动账本入口，或提供行为等价且有共同测试的实现。
7. `shares_delta` 始终使用带符号语义：买入为正，卖出和清仓为负。
8. 每个变动事件必须有可直接查询的业务日期和来源；不再用 `import_id=0` 作为无法联表的占位关联。
9. Excel/ZIP 的清仓比对只作用于同一文件快照来源的持仓，绝不能清除手工或快捷来源。
10. ZIP 必须先解析、去重并合并全部文件，再进行一次事务和一次来源内快照比对。
11. 任何解析错误都不得触发自动清仓；需要返回部分失败时，有效行和清仓行为必须分离。
12. 同一基金可以真实存在于多个平台或账户；不得仅按基金代码全局合并。
13. 未知账户的手工/快捷记录使用统一、稳定、可解释的身份规则，但不得未经确认自动吞并真实 Excel 账户。
14. staging 中 scheduler、启动回补、邮件、外部模型和自动任务继续关闭；按需公开基金信息获取不依赖开启调度器。

## 5. 推荐的最小实现结构

Luna 可在首次代码阅读后微调命名，但不得降低第 4 节不变量。

### 5.1 基金信息补全

- 在 `fund-advisor` 数据层增加一个可测试的基金信息获取函数或服务，同时返回基金名称、最新净值、净值日期和涨跌幅。
- 复用现有公开数据源和解析逻辑；避免复制策略层代码，不调用 LLM。
- HTTP 客户端、超时和响应解析必须可注入或可 mock。
- 成功后更新 `funds`，并同步修正同代码的活动持仓显示名称。
- 快捷导入 API 可改为异步，以便在写持仓前完成按需补全。
- `NavService` 刷新时补齐仍为占位值的基金名称，并安全修复符合第 4 节第 4 条条件的遗留零份额记录。

### 5.2 持仓来源和统一账本

- 优先采用加法式 Alembic 迁移，为持仓增加可区分手工/快捷/文件的来源字段，为变动事件增加业务日期和来源字段，并允许手工事件没有导入记录。
- 迁移必须兼容现有数据：文件导入事件从 `import_records.data_date` 回填日期；无有效导入关联的旧事件从创建日期回填。
- 不删除表、不删除列、不重命名既有列，不在本阶段运行生产迁移。
- 快照与日历查询应直接按变动业务日期读取，同时兼容迁移前的文件导入记录。
- 创建、删除、快捷导入和加减仓都写账本；Excel/ZIP 仍保留文件导入历史。

### 5.3 Excel/ZIP 安全与一致性

- 使用安全生成的临时文件名，不信任上传文件名作为路径。
- 采用流式或有上限读取；前端、Nginx 和后端使用一致且明确的大小限制。
- ZIP 解压前验证成员路径、成员数量、单文件大小和总解压量，只接受允许的 Excel 扩展名。
- 明确只支持 `.xlsx`，除非仓库现有锁和干净构建能够可靠加入受维护的 `.xls` 解析依赖；不得只改文案假装支持。
- 正确处理 openpyxl 返回的 `date`/`datetime` 和可能丢失前导零的数字基金代码。
- 按实际承诺实现多 Sheet；若文件结构只允许一个 Sheet，必须同步修正文档和界面。
- ZIP 文件列表去重并稳定排序；所有内容验证通过后一次合并和提交。
- 文件处理结束后按明确保留策略清理临时上传，测试必须证明异常路径也会清理。

### 5.4 API 与前端

- 持仓页新增和数据页快捷导入可以保留不同输入模式，但调用统一后端用例并返回一致状态。
- 快捷导入允许选择平台，不再硬编码支付宝。
- 输入基金代码后显示“正在获取 / 已获取 / 获取失败”，成功后预览名称、净值、日期和估算份额。
- 导入结果明确区分新增、更新、跳过、失败和等待修复；成功提示不能掩盖逐条失败。
- 快捷和手工操作出现在统一操作历史中；文件导入历史继续只记录文件批次。
- 不展示或记录真实账户、持仓文件内容和外部响应全文。

## 6. 允许修改的本地范围

预期白名单如下；如确需新增同层文件或测试，可在结果中说明，但不得进入策略与生产运维范围：

- `00_LUNA_START_HERE.md`
- `LUNA_HANDOFF.md`
- `07_LUNA_HOLDING_INGESTION_CORRECTNESS.md`
- `fund-advisor/PROJECT.md`
- `fund-advisor/CHANGELOG.md`
- `fund-advisor/docs/` 下与本修复直接相关的新文档或更新
- `fund-advisor/alembic/versions/` 下一个加法式迁移
- `fund-advisor/backend/api/holdings.py`
- `fund-advisor/backend/api/imports.py`
- `fund-advisor/backend/api/nav.py`
- `fund-advisor/backend/models/fund.py`
- `fund-advisor/backend/models/holding.py`
- `fund-advisor/backend/models/holding_change.py`
- `fund-advisor/backend/models/import_record.py`
- `fund-advisor/backend/schemas/holding.py`
- `fund-advisor/backend/schemas/holding_change.py`
- `fund-advisor/backend/schemas/import_result.py`
- `fund-advisor/backend/services/holding_service.py`
- `fund-advisor/backend/services/import_service.py`
- `fund-advisor/backend/services/nav_fetcher.py`
- `fund-advisor/backend/services/nav_service.py`
- `fund-advisor/backend/services/snapshot_service.py`
- `fund-advisor/backend/services/calendar_service.py`
- `fund-advisor/backend/services/excel_parser.py`
- `fund-advisor/backend/services/` 下本修复所需的新服务
- `fund-advisor/backend/tests/` 下新测试和本修复直接相关的测试更新
- `fund-advisor/frontend/nginx.conf`
- `fund-advisor/frontend/src/api/index.js`
- `fund-advisor/frontend/src/views/HoldingsView.vue`
- `fund-advisor/frontend/src/views/ImportView.vue`
- `fund-advisor/frontend/src/views/SettingsView.vue`
- `fund-advisor/frontend/` 下本修复直接需要的新测试文件

禁止修改：

- `fund-analyzer` 的策略、筛选、仓位、提示词和模型逻辑。
- `fund-analyzer/tests/test_position.py`。
- `fund-analyzer/tests/test_screener.py`。
- 风险阈值、回撤参数、择时规则和模型选择参数。
- 生产运维文件、OpenClaw、cron、systemd、生产 `.env` 和生产数据。

## 7. 本地实施阶段

### 7.1 分支与单写入者

- 在实时基线完全一致后，从当前 `HEAD` 创建 `codex/holding-ingestion-correctness`。
- 保留工作区现有五个差异，不使用 stash、restore、clean 或 reset。
- 分支创建后再次核对两个仍受保护测试文件哈希。
- Luna 成为唯一写入者；Sol 在 Luna 完成前只读取状态，不编辑共享文件。

### 7.2 实施顺序

1. 先写后端失败回归测试，覆盖第 8 节核心矩阵。
2. 实现基金信息补全和旧零份额安全修复。
3. 实现统一持仓身份、来源和变动账本。
4. 修复 Excel/ZIP 一次解析、来源内清仓、事务和上传安全。
5. 更新前端新增/快捷导入交互与错误反馈。
6. 更新 PROJECT、CHANGELOG 和当前交接文档，使能力描述与实现一致。
7. 运行定向测试、两套完整 Python 测试和前端生产构建。

不得为了让测试通过而调整既有策略语义或修改两个受保护测试文件。

## 8. 最低回归测试矩阵

### 8.1 基金信息与快捷导入

- 未知基金获取名称和净值成功后，名称不是占位值，份额等于金额除以净值。
- 名称源或净值源失败时，该条返回明确错误且数据库无新增持仓、无占位基金残留。
- 历史占位名称、零份额、正市值记录在成功刷新后保留原市值并反算份额。
- `cost_nav` 在用户未提供成本时保持空值。
- 请求默认日期按请求发生日计算，不使用进程启动日。
- 多条快捷导入中的单条失败不会污染成功记录，Session 可继续使用；事务语义与返回结果一致。

### 8.2 身份与账本

- 手工新增和快捷导入使用统一稳定的未知账户身份规则。
- 同基金不同平台或真实账户保持不同持仓。
- 手工新增、快捷导入、删除、加仓、减仓和清仓都产生可按业务日期查询的变动事件。
- 加仓 `shares_delta > 0`；减仓与清仓 `shares_delta < 0`。
- 快照净资金流和收益日历能读取手工事件，不依赖伪造的 `import_id=0`。

### 8.3 Excel/ZIP

- Excel 导入不会清除手工或快捷来源持仓。
- 两个 Excel 的 ZIP 导入后两组持仓同时存在，不互相清仓。
- ZIP 顶层文件只处理一次，顺序稳定。
- 解析错误时不执行清仓。
- 重复文件幂等，不产生重复持仓或重复事件。
- 数字型基金代码恢复为六位字符串；`date`、`datetime` 和允许的日期字符串都正确解析。
- 多 Sheet 行为与文档一致。
- 路径穿越、超成员数、超单文件、超总解压量和超上传大小被拒绝，且临时文件清理。

### 8.4 全量门禁

执行命令前逐条用中文解释用途。至少完成：

- 新增定向后端测试全部通过。
- `fund-advisor/backend/tests` 使用 `-p no:cacheprovider` 全部通过。
- `fund-analyzer/tests` 使用 `-p no:cacheprovider` 运行完整测试；当前工作区包含两个既有测试文件改动，结果必须单独说明，不能把它们纳入本次修改。
- 前端 `npm ci` 和生产构建在干净环境通过；若本机权限或 Docker Hub 阻塞，保留第一个可操作错误并停止，不用已有 `node_modules` 冒充干净证明。
- Alembic 从空 MySQL 升级到 head，并从当前 staging 旧 schema 升级到新 head 的方案可验证；本阶段不得连接服务器数据库。
- 敏感信息检查和 `git diff --check` 通过。
- 两个仍受保护测试文件哈希与开始一致，暂存区为空。

## 9. 本阶段禁止的外部动作

- 不暂存、不提交、不推送 GitHub。
- 不修改、停止、重启或替换当前 staging 容器、网络、卷和数据库。
- 不把用户刚才的 staging 测试记录复制到本地，不读取或输出真实持仓内容。
- 不连接或操作生产数据库，不创建生产备份。
- 不修改生产 Git 工作区、三个生产热修、OpenClaw、cron、systemd、`tat_agent.service` 或生产流量。
- 不执行 `reset --hard`、`clean`、强制推送、覆盖式同步或删除操作。

## 10. 立即停止条件

出现任一情况立即停止并汇报：

- 实时 Git 基线、两个受保护文件哈希或单写入者状态不符。
- 正确修复需要调整策略参数、重写 P0 或修改两个仍受保护测试文件。
- 需要删除表、删除列、全库重写历史持仓或读取真实数据才能继续。
- 无法区分手工来源和文件来源，且继续会误清持仓。
- 公开基金信息源失败，且代码无法提供安全的失败降级。
- 新增测试暴露本执行令之外的第三条跨层业务语义，需要扩大范围。
- 本地测试、迁移或构建失败且无法在当前白名单内解释和修复。
- 需要服务器写入、推送、提交或数据库操作才能继续本地阶段。

## 11. Luna 精简结果格式

完成后只汇报：

```text
结果：完成 / 停止 / 需要确认
基线：分支、HEAD、暂存区、两个受保护文件哈希
写入：实际修改和新增文件，按数据模型/服务/API/前端/测试/文档分组
正确性：逐条对应第 4 节不变量
验收：定向测试、两套 Python 全量、前端构建、迁移、敏感信息和 diff 检查
外部状态：明确写“未操作 GitHub、服务器 staging、生产、OpenClaw 和数据库”
阻塞：无或第一个可操作问题
下一授权：暂存提交、GitHub 推送和新 SHA staging 更新方案；不得自行执行
```

不要返回完整日志、真实持仓、上传文件内容、外部响应正文、服务器地址或秘密。

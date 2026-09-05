# Luna 持仓正确性修复阶段 B1：统一写账本与加法迁移

> 编写日期：2026-09-04
> 仓库：`E:\myfund11111`
> 前置：阶段 A 已通过代码验收，运行验收待隔离 staging
> 本阶段：只完成模型、加法迁移和持仓变动写入；完成后停止

## 1. 目标

解决当前“页面写成功，但收益日历和资金流看不到或方向错误”的写入侧问题：

1. `HoldingChange.import_id` 不再强制依赖文件导入记录，手工和快捷事件使用空关联，不再写 `0`。
2. 每个事件直接保存 `business_date` 和 `source_type`，读侧不再需要通过 `import_records` 才能知道日期。
3. `FundHolding` 保存 `source_type`，至少区分 `file`、`manual`、`quick` 和兼容旧数据的 `legacy`。
4. 手工新增、快捷新增/更新、手工加仓/减仓、删除/清仓和文件导入都写入结构一致的事件。
5. `shares_delta` 统一为带符号值：买入为正，卖出和清仓为负。
6. 本阶段只建立正确写入，不改日历和快照读取算法；读侧留给 B2。

## 2. 开始基线与保护

- 分支必须为 `codex/holding-ingestion-correctness`。
- `HEAD` 必须为 `6a7744577d76e8ea40fbef7d83700a2c202b815f`，暂存区为空。
- 保留当前全部未提交差异，不 reset、restore、stash、clean 或格式化无关文件。
- 阶段 A 文件只读；若 B1 必须复用统一事件辅助函数，可最小修改 `holding_service.py`，不得改变已验收的基金补全语义。
- 两个受保护测试文件不得修改，其 SHA256 必须保持：
  - `fund-analyzer/tests/test_position.py`：`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`
  - `fund-analyzer/tests/test_screener.py`：`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`

## 3. 允许修改

- `fund-advisor/backend/models/holding.py`
- `fund-advisor/backend/models/holding_change.py`
- `fund-advisor/backend/schemas/holding.py`
- `fund-advisor/backend/schemas/holding_change.py`
- `fund-advisor/backend/services/holding_service.py`
- `fund-advisor/backend/services/import_service.py`，只允许补事件字段和事务一致性，不处理 ZIP/Excel 合并与上传逻辑
- `fund-advisor/alembic/versions/` 下一个新的加法式迁移
- `fund-advisor/backend/tests/` 下 B1 虚构数据回归测试
- 本文件中仅追加实际结果

其他文件全部只读。特别禁止修改 `calendar_service.py`、`snapshot_service.py`、前端、策略文件和两个受保护测试文件。

## 4. 数据模型与迁移要求

迁移必须从当前唯一 head `a1b2c3d4e5f6` 继续，采用加法式和可回滚设计：

### 4.1 `fund_holdings`

- 新增 `source_type`，长度足以保存 `file/manual/quick/legacy`。
- 现有 `last_import_id` 有有效导入记录的行回填为 `file`。
- 无有效导入关联的旧行回填为 `legacy`；不得根据平台名称猜测为手工或快捷。
- 回填后列不可为空，并建立必要索引；不得改变现有唯一键和真实账户字段。

### 4.2 `holding_changes`

- `import_id` 改为可空；把旧的 `import_id=0` 安全转换为空。
- 新增不可空 `business_date`：有有效 `import_records` 关联时从 `data_date` 回填，否则从 `created_at` 的日期回填。
- 新增不可空 `source_type`：有有效导入关联时为 `file`，无有效关联的旧事件为 `legacy`。
- 为按业务日期查询和按持仓重建历史增加最小必要索引，建议至少覆盖 `business_date` 及 `(holding_id, business_date, id)`。
- 不删除表、列或历史记录，不重命名既有列，不运行服务器迁移。
- downgrade 只移除本次新增索引/列并恢复 `import_id` 约束前，必须明确处理空值；若无法无损恢复，写清限制并停止，不伪造导入编号。

## 5. 写事件规则

统一通过一个清晰、可测试的内部辅助函数构造事件，字段至少包括：

- `holding_id`、基金代码、规范名称、平台
- `change_type`
- `shares_before`、`shares_after`、带符号 `shares_delta`
- `nav_at_change`、`mv_before`、`mv_after`
- `business_date`、`source_type`
- 文件导入才设置真实 `import_id`；手工和快捷保持空

具体入口：

- 手工新增：`new`，`source_type=manual`，日期使用 `share_date`。
- 快捷新增：`new`，`source_type=quick`，日期使用请求 `share_date`。
- 快捷更新：根据份额变化写 `increase/decrease/clear`；无份额变化不重复写事件。
- 加仓：`increase`，正 `shares_delta`。
- 减仓：`decrease` 或 `clear`，负 `shares_delta`。
- 删除：软删除并写 `clear`，负值等于删除前份额。
- 文件导入：保留真实 `import_id`，`source_type=file`，`business_date` 使用该批 `data_date`。

一次业务操作中的持仓变更和事件必须同事务提交；失败整体回滚。不要为手工操作创建伪造的 `ImportRecord`。

## 6. 最低回归测试

- 迁移升级后列、可空性、索引和回填 SQL 符合第 4 节。
- 手工新增写 `manual/new` 事件且 `import_id is None`。
- 快捷新增和更新写 `quick` 事件，日期来自请求。
- 加仓 delta 为正；减仓和清仓 delta 为负。
- 删除写清仓事件并与软删除同事务。
- 文件导入事件保留真实 import_id、文件 data_date 和 `file` 来源。
- 任一事件写入失败时对应持仓修改回滚。
- 同一天多事件可用 `(business_date, id)` 稳定排序。
- 不再产生新的 `import_id=0`。

测试只使用虚构数据。若本机无 pytest，完成 AST/迁移脚本静态检查并如实记录；完整测试留待隔离 staging 总门禁。

## 7. 禁止与停止条件

- 不修改日历/快照读侧，不提前执行 B2。
- 不处理 ZIP/Excel 清仓、解压、上传和多 Sheet，不提前执行 C。
- 不修改前端，不安装依赖。
- 不暂存、提交、推送，不操作服务器、staging、生产数据库、容器、OpenClaw、cron 或 systemd。
- 若需要破坏式迁移、伪造 ImportRecord、猜测旧数据来源或修改策略参数，立即停止。
- 若当前差异或保护哈希不符，立即停止。

## 8. 完成格式

```text
结果：完成 / 停止 / 需要确认
基线：分支、HEAD、暂存区、保护哈希
模型：新增列、可空性、索引和回填规则
写入：各入口的事件类型、日期、来源、delta 符号和事务
测试：命令、结果或第一个环境阻塞
文件：实际修改与新增文件
外部状态：未操作 GitHub、服务器、staging、生产、数据库和 OpenClaw
下一步：等待 Sol 审查，不自行进入 B2
```

## 9. Sol 第一次只读验收与返修要求

> 验收时间：2026-09-04
> 结论：B1 已完成主体实现，但存在会影响真实迁移和资金流的错误，暂不进入 B2。

已通过：

- 新迁移从当前 head `a1b2c3d4e5f6` 继续，没有删除或重命名既有列。
- ORM 已允许事件 `import_id` 为空，并增加 `business_date`、`source_type` 和必要索引。
- 手工、快捷和文件入口已开始使用统一事件构造函数。
- 普通减仓已改为负 `shares_delta`，文件清仓也保持负值。
- 两个受保护测试文件哈希未变化，暂存区为空。
- B1 涉及的 Python 文件只读 AST 解析通过，`git diff --check` 通过。

必须返修：

1. **MySQL 迁移兼容**：本项目 staging/生产使用 MySQL。当前迁移中的所有 `op.alter_column(...)` 必须提供正确的 `existing_type`，以及 Alembic/MySQL 所需的既有属性，避免生成不完整的 `MODIFY COLUMN`。至少覆盖 `fund_holdings.source_type`、`holding_changes.import_id`、`holding_changes.business_date`、`holding_changes.source_type` 和 downgrade 的 `import_id`。
2. **不得伪造历史业务日期**：迁移不能把无法从导入日期或 `created_at` 得到日期的旧事件静默写成 `CURRENT_DATE`。在任何 DDL 前先只读检查这类无法回填的行；若存在则在迁移未改结构前明确失败。正常回填后不得保留 `CURRENT_DATE` 兜底。
3. **文件事件不得用今天兜底**：`import_service.py` 三处 `business_date or date.today()` 必须移除。文件没有有效 `data_date` 时不得合并、清仓或写事件，应返回/记录明确解析错误；绝不能把导入日伪造成执行日。
4. **超额减仓/清仓差值**：`record_change` 在请求减仓份额超过当前份额、最终截为零时，事件 `shares_delta` 必须等于 `new_shares - old_shares`，即 `-old_shares`，不能记录大于实际持仓的请求份额。事件 `mv_after` 必须与最终持仓一致。
5. **真实入口测试**：当前 B1 新测试只覆盖统一 helper 和 ORM 列声明，不满足第 6 节。至少补手工新增、快捷新增/更新、普通减仓、超额减仓清仓、删除、文件新增/变更、事件失败回滚和不再产生 `HoldingChange(import_id=0)`；夹具必须观察实际 service 入口写入对象与事务，不得只直接调用 helper。
6. **迁移静态断言**：增加不依赖服务器的迁移检查，确认 revision 链、MySQL `existing_type`、无 `CURRENT_DATE` 伪日期、索引和空 import_id 转换。真实空库升级与旧 schema 升级仍留给 staging 门禁。

可接受但必须记录的限制：一旦产生手工/快捷空 `import_id` 事件，数据库 schema downgrade 无法无损恢复旧的非空约束。迁移可以拒绝这种破坏性 downgrade；应用回滚方案应保留前向兼容 schema，不得伪造导入编号。

返修范围仍限于第 3 节。完成后按第 8 节汇报并停止，不进入 B2。

## 10. Sol 第二次只读验收与最后微返修

> 验收时间：2026-09-04
> 结论：第 9 节的迁移、日期和超额清仓问题已修复；完成本节事务微返修后即可结束 B1。

已通过：

- MySQL `alter_column` 已补齐 `existing_type` 和既有可空性。
- 无法回填历史业务日期时会在 DDL 前停止，不再使用 `CURRENT_DATE` 伪造。
- 文件入口缺少 `data_date` 时拒绝合并，不再以执行日兜底。
- 超额减仓清仓的 `shares_delta` 已改为 `new_shares - old_shares`，`mv_after` 与最终零持仓一致。
- 已新增手工、快捷、删除、文件与迁移静态测试。

最后必须修复：

1. `create_holding` 的 Fund flush、Holding flush、事件 add 和 commit 必须全部位于同一个 `try/except` 回滚边界内；当前两个 flush 在 `try` 外，flush 失败不会调用 rollback。
2. `record_change` 的持仓字段修改、flush、事件 add 和 commit 必须处于同一个 `try/except` 回滚边界；当前持仓 flush 在 `try` 外。
3. `delete_holding` 对已清仓记录必须拒绝或明确幂等，不能再次写零差值 clear 事件。
4. 补测试：手工新增 flush 失败会 rollback；加减仓 flush 失败会 rollback；普通减仓写负 delta 且不清仓；重复删除不产生第二条 clear 事件；文件“已有持仓更新”事件保留真实 import_id、business_date 和带符号 delta。
5. 不扩大到 `plan.py`、日历、快照、Excel/ZIP 清仓或前端；这些仍由后续阶段分别处理。

完成后重新执行 AST、`git diff --check` 和保护哈希检查，按第 8 节格式汇报并停止。

## 11. Sol 第三次只读验收：第 10 节未落地

> 验收时间：2026-09-04
> 结论：本次“执行完成”未产生第 10 节要求的代码与测试变化，B1 仍未通过，不得进入 B2。

现场证据：

- `create_holding` 中创建 Fund 后的 `flush()` 和创建 Holding 后的 `flush()` 仍位于 `try/except` 之外。
- `record_change` 中持仓字段修改和 `flush()` 仍位于 `try/except` 之外。
- `delete_holding` 仍未拒绝或幂等处理已清仓持仓，重复调用仍可能生成第二条零差值 `clear` 事件。
- 回归文件仍止于原有“事件 add 失败会 rollback”测试，没有第 10 节要求的两类 flush 失败、普通减仓、重复删除和文件已有持仓更新测试。
- 源码与测试文件的最后修改时间早于第 10 节写入时间，说明执行端很可能读取了旧上下文或没有执行到该节。
- 分支、HEAD、空暂存区、两个受保护测试文件哈希和 `git diff --check` 均仍符合基线。

重新执行时只完成以下原子任务，不重复阶段 A 或第 9 节：

1. 把 `create_holding` 的两个 `flush()`、事件写入、提交和刷新放入同一个回滚边界。
2. 把 `record_change` 的持仓修改、`flush()`、事件写入、提交和刷新放入同一个回滚边界。
3. 让 `delete_holding` 对非活动或零份额持仓拒绝或幂等返回，且不新增第二条事件。
4. 补齐第 10 节列出的五类真实入口测试。
5. 执行 AST、`git diff --check`、保护哈希检查；本机没有 pytest 时如实记录，不安装依赖。

完成后在本节末尾追加实际结果并停止。不得修改其他文件，不得进入 B2、暂存、提交、推送或操作服务器。

### 第 11 节实际结果（2026-09-04）

- 已完成：`create_holding` 的 Fund flush、Holding flush、事件 add、commit 和 refresh 已纳入同一回滚边界。
- 已完成：`record_change` 的持仓修改、flush、事件 add、commit 和 refresh 已纳入同一回滚边界。
- 已完成：重复删除非活动或零份额持仓会拒绝，不新增第二条 `clear` 事件。
- 已完成：补充手工新增、快捷新增/更新、普通减仓、超额清仓、重复删除、文件已有持仓更新以及 flush 失败回滚测试。
- 验收：8 个相关 Python 文件 AST 解析 `AST_PARSE=OK`；`git diff --check` 通过；暂存区为空；两个受保护测试文件 SHA256 与基线一致。
- 环境限制：本机 pytest 不可用，未安装依赖；未宣称 pytest 通过。
- 外部状态：未进入 B2，未暂存、提交、推送，未操作服务器、staging、生产、数据库、OpenClaw、cron 或 systemd。

## 12. Sol 最终交叉入口审查：来源所有权补漏

> 验收时间：2026-09-04
> 结论：第 10、11 节事务与测试要求已落地；还需修复一个会导致文件导入误清人工维护持仓的来源所有权漏洞。

问题链路：

1. 文件导入创建的持仓带有 `source_type=file` 和非空 `last_import_id`。
2. 快捷录入更新该持仓时会改为 `source_type=quick` 并清空 `last_import_id`，但 `record_change` 手工加减仓没有做等价转换。
3. 文件快照自动清仓目前只判断 `last_import_id is not None`，没有同时要求当前 `source_type=file`。
4. 因而一个已经由用户手工加减仓接管的历史文件持仓，仍可能在后续文件中缺席时被自动清仓。

只做以下修复：

- 在 `record_change` 的同一事务 `try` 内，把成功手工加减仓后的持仓设为 `source_type=manual`，并清空 `last_import_id`；失败回滚时必须与份额修改一起回滚。
- 文件快照自动清仓必须只处理当前 `source_type == "file"` 且拥有有效 `last_import_id` 的活动持仓；`manual`、`quick`、`legacy` 均跳过。
- 增加回归测试：历史文件持仓经手工加减仓后变为 manual、清空导入归属；后续文件快照缺少该持仓时不清仓、不生成 file clear 事件。
- 保留现有事务、delta、日期和迁移语义，不修改日历、快照、Excel/ZIP 聚合、前端或策略。

完成后追加实际结果，执行 AST、`git diff --check` 和保护哈希检查并停止。不得进入 B2、暂存、提交、推送或操作服务器。

### 第 12 节实际结果（2026-09-04）

- 已完成：手工加减仓在同一事务内将持仓来源接管为 `manual`，并清空 `last_import_id`。
- 已完成：文件快照清仓仅处理 `source_type=file` 且拥有有效导入归属的活动持仓。
- 已完成：补充回归测试，验证文件持仓经手工变动后不会被后续缺失快照清仓，也不会生成 file clear 事件。
- 验收：3 个本轮相关 Python 文件 AST 解析 `AST_PARSE=OK`；`git diff --check` 通过；暂存区为空；两个受保护文件 SHA256 与基线一致。
- 外部状态：未进入 B2，未暂存、提交、推送，未操作服务器、staging、生产、数据库、OpenClaw、cron 或 systemd。

## 13. Sol 最终验收结论

> 验收日期：2026-09-05
> 结论：B1 代码级验收通过，可以进入 B2；运行级验收仍留待隔离 staging。

- 统一事件模型、加法迁移、带符号差值、事务回滚和来源所有权边界均已复核。
- 手工接管文件持仓后会改为 `manual` 并清空 `last_import_id`；文件快照清仓只处理当前 `file` 来源。
- 定向测试文件现有 27 个测试定义；8 个 B1 相关 Python 文件 AST 解析通过。
- `git diff --check` 通过，暂存区为空，两个受保护测试文件哈希与基线一致。
- 本机可用 Python 不含 pytest，因此没有宣称运行测试通过；真实 MySQL 迁移和完整 Python 门禁必须在隔离 staging 执行。
- 未暂存、提交、推送或操作 GitHub、服务器、staging、生产、数据库及 OpenClaw。

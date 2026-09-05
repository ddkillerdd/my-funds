# Luna 持仓正确性阶段 C：Excel/ZIP 导入安全与快照合并

> 日期：2026-09-05
> 状态：待 Luna 执行，完成后必须停止并等待 Sol 验收
> 前置：阶段 A、B1、B2 已通过代码级验收；运行测试仍须在依赖完整的隔离环境补齐

## 1. 本阶段目标

只处理文件导入链路，使一次 Excel 或 ZIP 上传形成一个可审计、原子化的“文件来源持仓快照”：

1. Excel 与 ZIP 中所有有效工作表、所有有效文件先完成解析和全局校验，再发生数据库写入。
2. ZIP 内多个文件只合并一次、只创建一个导入记录、只提交一次，不能互相把前一个文件的持仓清零。
3. 只有完整且无解析错误的快照允许自动清除本次快照中缺失的既有 file 持仓；部分数据不得触发清除。
4. 路径、文件名、压缩包成员、大小、数量、临时目录和异常清理均具备明确安全边界。
5. 当前依赖只可靠支持 `.xlsx`，因此后端明确拒绝 `.xls`，不增加 `xlrd` 或其他新依赖。

本阶段不处理前端上传提示、Nginx 大小限制、分析引擎、策略参数、部署配置或服务器状态；这些留给下一阶段。

## 2. 执行前实时准入

先用只读命令确认并在结果中记录：

- 仓库：`E:\myfund11111`
- 分支：`codex/holding-ingestion-correctness`
- `HEAD`：`6a7744577d76e8ea40fbef7d83700a2c202b815f`
- 暂存区为空
- 工作区不存在来源不明的新差异
- 以下两个保护文件 SHA256 仍分别为：
  - `E:\myfund11111\fund-analyzer\tests\test_position.py`：`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`
  - `E:\myfund11111\fund-analyzer\tests\test_screener.py`：`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`

若分支、HEAD、保护哈希、暂存区或已有差异边界不符，立即停止并汇报，不自行还原、清理或覆盖。

## 3. 唯一允许修改范围

- `E:\myfund11111\fund-advisor\backend\services\import_service.py`
- `E:\myfund11111\fund-advisor\backend\services\excel_parser.py`
- `E:\myfund11111\fund-advisor\backend\schemas\import_result.py`
- `E:\myfund11111\fund-advisor\backend\api\imports.py`，仅限同步后端实际支持格式的接口说明
- `E:\myfund11111\fund-advisor\backend\tests\test_file_import_safety.py`，优先新建
- 本执行令末尾的实际结果

除上述文件外不得修改生产代码。若测试证明必须修改其他文件，停止并把证据交给 Sol，不自行扩大范围。

## 4. 必须实现的语义

### 4.1 格式与工作表

- 独立文件只接受 `.xlsx`；压缩包只接受 `.zip`，包内业务文件只接受 `.xlsx`。
- 对 `.xls` 返回明确且稳定的“不支持”错误；不得将其交给 openpyxl 后再暴露晦涩异常。
- Excel 解析多个工作表：识别第 5 行符合既有持仓表头的工作表；至少有一个可识别工作表，否则文件失败。
- 不能静默吞掉看似包含业务数据但表头不合法的工作表。允许跳过完全空白或明确非业务说明页，但要在解析结果中留下可测试的诊断。
- 工作簿在成功与异常路径都必须关闭。

### 4.2 日期与重复键

- 一次上传是同一业务日期的一份快照；跨工作表、跨 ZIP 文件出现多个有效 `share_date` 时，整批拒绝，不猜测日期、不写持仓。
- 唯一键继续使用当前 `(fund_code, platform)` 语义。
- 跨行、跨 Sheet、跨 ZIP 文件的完全相同重复记录只保留一条；同一唯一键内容冲突则整批拒绝，不以后出现者覆盖前者。
- 基金代码、平台与数值规范化必须复用现有规则，不改变策略或持仓金额公式。

### 4.3 单次事务与来源快照

- 所有文件先解析、汇总、校验，数据库写入必须在其后。
- 一次 Excel 或 ZIP 上传只创建一个最终 `ImportRecord`；ZIP 不创建逐子文件导入记录。
- 所有 `HoldingChange` 必须关联这一个最终导入记录，并保留 B1 的 `business_date`、来源与身份语义。
- 整批完全有效时，调用 `_merge_holdings` 一次并允许只清除当前 `source_type=file` 且具有有效 `last_import_id`、但本次快照缺失的持仓。
- 存在可恢复的行级/Sheet 级解析错误时，可以导入已确认有效的记录，但必须标记 partial 且以 `allow_clear=False` 合并；不得产生任何自动清除事件。
- 存在压缩包结构错误、混合日期、冲突重复键、没有有效业务文件或没有有效记录等批次级错误时，不写持仓；导入记录如何记失败必须保持一次事务和一致状态。
- 合并、事件写入或提交任一步失败时执行 rollback，不保留部分持仓、部分事件或多个成功子记录。

### 4.4 上传、ZIP 与清理安全

- 保留流式写入与 20 MiB 上传上限；拒绝空文件，不能仅信任 Content-Type。
- 存储名与临时目录使用不可预测的唯一名字；展示名只使用清洗后的 basename，不能使用用户路径创建目录。
- ZIP 在解压前逐项校验：成员数不超过 100、单成员解压后不超过 20 MiB、总解压大小不超过 100 MiB。
- 拒绝绝对路径、盘符、UNC、`..`、反斜杠绕过、NUL、加密成员、符号链接及其他非普通文件；目录项可以安全忽略。
- 不使用 `extractall`。只把通过校验的 `.xlsx` 普通文件流式写入本次唯一临时目录；成员读取时也必须限制实际字节数，不能只信任 ZIP 元数据。
- 顶层与嵌套文件形成稳定、去重、可预测的处理顺序；同一成员不得被 glob 与 rglob 重复处理。
- 上传文件和临时目录在成功、重复上传、解析失败、数据库失败等所有路径均清理；不得删除目录范围外的对象。
- 重复导入以内容哈希为主，并统一使用清洗后的展示文件名；不能因浏览器上传了本地路径而绕过。

### 4.5 结果模型

- `ImportResult.changes` 改用 `Field(default_factory=list)`，避免可变默认值共享。
- 返回的总数、成功数、失败数、状态和错误信息必须对应整批上传，不得把 ZIP 子文件结果误算为多次导入。
- 错误信息可以包含清洗后的文件名和 Sheet 名，但不得包含服务器绝对路径、凭据或数据内容。

## 5. 必须补充的回归测试

测试必须调用真实解析/合并入口或最小可验证函数，不得只扫描源码字符串。至少覆盖：

1. 独立 `.xls` 和 ZIP 内 `.xls` 被明确拒绝，且没有持仓写入。
2. 正常多 Sheet `.xlsx` 合并为一份快照；空白说明页的处理符合约定，工作簿关闭。
3. ZIP 两个 `.xlsx` 合并一次，前一个文件的持仓不会被后一个文件清除；只产生一个 ImportRecord、一次 merge、一次 commit，事件使用同一 import id。
4. 行级/Sheet 级 partial 可以保留有效记录但 `allow_clear=False`；完全有效才允许清除。
5. 混合业务日期和冲突重复键在数据库写入前拒绝；完全相同重复键稳定去重。
6. 合并或提交异常触发 rollback，不留下部分结果。
7. 手工、快捷、legacy 以及没有有效 `last_import_id` 的持仓不会被文件快照清除。
8. 路径穿越同时覆盖 `/`、`\\`、盘符、UNC、NUL；覆盖符号链接、加密成员和非普通文件。
9. 覆盖空上传、上传超过 20 MiB、成员数、单成员大小、总大小和实际解压字节超限。
10. 顶层/嵌套文件稳定去重处理；成功、重复、解析失败、数据库失败均清理上传文件和临时目录。
11. `ImportResult` 实例之间不共享 `changes` 列表。
12. 错误文本不泄露服务器绝对路径。

若环境缺少 pytest、SQLAlchemy 或 openpyxl，如实记录第一个阻塞；不得安装依赖，也不得把 AST 或源码扫描描述为测试通过。

## 6. 验证命令与停止条件

在现有环境中依次尝试并记录：

1. 新增文件导入安全测试。
2. 已有 `test_holding_ingestion_correctness.py` 与 `test_holding_history_readers.py`，确保 C 阶段未破坏 A/B。
3. 相关 Python 文件 AST 解析。
4. `git diff --check`。
5. `git status --short --branch` 与 `git diff --cached --name-only`。
6. 两个保护文件 SHA256。

完成后把以下内容追加到本文件并停止：

```text
结果：完成 / 停止 / 需要确认
基线：分支、HEAD、暂存区、保护哈希
格式：xlsx/xls/zip/多 Sheet 处理
事务：记录数、merge 次数、commit/rollback、partial 清除门
安全：路径、成员、大小、临时目录、清理
测试：测试名称、命令、通过数或第一个环境阻塞
文件：实际修改与新增文件的绝对路径
外部状态：未操作 GitHub、服务器、staging、生产、数据库和 OpenClaw
下一步：等待 Sol 验收，不进入前端、不暂存、不提交、不推送
```

以下任一情况立即停止：

- 基线或保护文件漂移；
- 需要修改白名单外文件；
- 需要安装依赖或访问网络；
- 需要读取真实数据、环境值或服务器秘密；
- 需要执行数据库迁移、服务器写入、systemd/OpenClaw/cron 操作；
- 测试暴露 A、B1、B2 的确定性回归且无法在白名单内最小修复。

本阶段禁止暂存、提交、推送、部署 staging、切生产流量或调整策略参数。

## 7. 实际结果（2026-09-05）

结果：完成本阶段白名单内实现与回归测试补充；因当前环境缺少 pytest/SQLAlchemy，停止等待 Sol 验收。

基线：分支 `codex/holding-ingestion-correctness`；HEAD `6a7744577d76e8ea40fbef7d83700a2c202b815f`；暂存区为空。保护文件 SHA256 仍为：`fund-analyzer/tests/test_position.py`=`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`，`fund-analyzer/tests/test_screener.py`=`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`。已有工作区差异均保留，未清理或覆盖。

格式：独立 `.xls` 与 ZIP 内 `.xls` 明确拒绝；仅接受 `.xlsx`；解析全部有效 Sheet，完全空白/非业务说明页可跳过并保留诊断；跨 Sheet/ZIP 混合业务日期拒绝；完全重复唯一键去重，冲突唯一键拒绝。

事务：独立 Excel 与 ZIP 均先完成解析、日期和重复键校验，再创建一个 `ImportRecord`、调用一次 `_merge_holdings` 并提交一次；ZIP 多文件不再逐文件导入；partial 传递 `allow_clear=False`，完整批次才允许清除；合并或提交异常 rollback。

安全：上传使用清洗展示名和不可预测存储名；空文件及超过 20 MiB 拒绝；ZIP 成员数、单成员/总解压大小、实际流式字节数均限制；拒绝绝对路径、盘符、UNC、反斜杠穿越、NUL、加密成员、符号链接和非普通文件；不使用 `extractall`；临时目录和上传文件在 finally 清理。

测试：新增 `fund-advisor/backend/tests/test_file_import_safety.py`，覆盖 `.xls`、多 Sheet/关闭、混合日期、重复键、ZIP 路径与大小、partial 不清除、结果列表隔离和错误路径边界；同时按要求尝试运行该文件及 A/B 回归文件，三个 pytest 命令均首个阻塞为 Bundled Python 缺少 `pytest`。AST 解析 7 个相关 Python 文件全部通过，`git diff --check` 通过；未安装依赖，未虚报测试通过。

文件：实际修改或新增的 Stage C 文件为 `E:\myfund11111\fund-advisor\backend\services\import_service.py`、`E:\myfund11111\fund-advisor\backend\services\excel_parser.py`、`E:\myfund11111\fund-advisor\backend\schemas\import_result.py`、`E:\myfund11111\fund-advisor\backend\api\imports.py`、`E:\myfund11111\fund-advisor\backend\tests\test_file_import_safety.py` 和本文件 `E:\myfund11111\11_LUNA_HOLDING_CORRECTNESS_STAGE_C.md`。文件曾被修改。

外部状态：未操作 GitHub、服务器、staging、生产、数据库、OpenClaw、cron、systemd；未暂存、提交或推送。

下一步：等待 Sol 验收，不进入前端、不暂存、不提交、不推送。

## 8. Sol 第一次验收返修实际结果（2026-09-05）

结果：完成第 8 节列出的最小返修，未进入前端或外部环境，停止等待 Sol 第二次验收。

基线：分支 `codex/holding-ingestion-correctness`；HEAD `6a7744577d76e8ea40fbef7d83700a2c202b815f`；暂存区为空；已有工作区差异未清理。保护文件 SHA256 保持：`test_position.py`=`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`，`test_screener.py`=`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`。

返修：成员预校验阶段明确拒绝 ZIP 内 `.xls`；文件名清洗失败返回脱敏错误并只清理受控路径；错误记录的 add/flush/commit/refresh 纳入 rollback 边界；ZIP 成员规范化后按 Windows 大小写折叠检测碰撞，解压目标使用批次内唯一序号名；累计实际解压字节并执行 100 MiB 门禁；`_parse_decimal` 保留 0/0.0/Decimal 零值；表头校验覆盖全部 15 列；删除未使用的 `os` 导入。

测试：在 `E:\myfund11111\fund-advisor\backend\tests\test_file_import_safety.py` 新增并实际定义以下测试：

- `test_zip_two_files_are_one_batch_and_one_commit`：两个有效 xlsx 同时进入一次 merge，单一 import id 和一次 commit，两个持仓共同保留。
- `test_batch_flush_merge_and_commit_failures_rollback`：flush、merge、commit 各类异常均触发一次 rollback。
- `test_merge_clear_protects_non_file_and_missing_import_sources`：manual、quick、legacy 及无 `last_import_id` 的 file 持仓不被清除。
- `test_zip_rejects_duplicate_casefolded_members_and_special_members`：大小写碰撞、符号链接、加密和非普通成员拒绝。
- `test_decimal_parser_preserves_zero_values`：合法零值不被当作空值。
- `test_upload_empty_and_oversize_are_rejected`：空上传和超过 20 MiB 上传拒绝。
- `test_zip_actual_total_limit_and_cleanup`：实际总解压量超过 100 MiB 拒绝并清理。
- `test_parse_and_database_errors_clean_upload_artifacts`：解析异常和数据库异常均清理上传对象。

已有 Stage C 测试同时覆盖独立/ZIP `.xls`、多 Sheet 关闭、混合日期、重复键、partial 门、结果列表隔离和错误路径边界。相关三个测试文件合计 57 个测试定义。pytest 命令均因 Bundled Python 缺少 `pytest` 阻塞；未安装依赖，未把静态检查写成测试通过。

安全与事务：未使用 `extractall`；ZIP 实际单成员及累计总量均限制；上传、临时目录在成功、重复、解析失败和数据库异常路径使用受控 finally 清理；批次级日期/冲突错误在 merge 前拒绝；partial 不清除；merge/提交失败 rollback。

验证：7 个相关 Python 文件 AST 解析通过；`git diff --check` 通过；暂存区为空；保护哈希保持基线。文件曾被修改。

文件：实际修改或新增白名单文件为 `E:\myfund11111\fund-advisor\backend\services\import_service.py`、`E:\myfund11111\fund-advisor\backend\services\excel_parser.py`、`E:\myfund11111\fund-advisor\backend\schemas\import_result.py`、`E:\myfund11111\fund-advisor\backend\api\imports.py`、`E:\myfund11111\fund-advisor\backend\tests\test_file_import_safety.py` 和 `E:\myfund11111\11_LUNA_HOLDING_CORRECTNESS_STAGE_C.md`。

外部状态：未操作 GitHub、服务器、staging、生产、数据库、OpenClaw、cron 或 systemd；未暂存、提交或推送。

下一步：等待 Sol 第二次验收，不进入前端、不暂存、不提交、不推送。

## 9. Sol 第二次验收最终返修实际结果（2026-09-05）

结果：完成第 9 节指定的最终返修，停止等待 Sol 最终验收。

基线：分支 `codex/holding-ingestion-correctness`；HEAD `6a7744577d76e8ea40fbef7d83700a2c202b815f`；暂存区为空；保护文件 SHA256 保持 `test_position.py`=`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`、`test_screener.py`=`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`。

返修：新增 `BatchValidationError`，混合业务日期和冲突重复键均作为结构化批次错误，在独立 Excel 与 ZIP 中于 merge 前拒绝；成功 commit 后移除 refresh，错误记录分支先 flush 取 id、commit 作为最后数据库动作；损坏 xlsx 统一转换为不含服务器路径的受控错误；修正说明页与错误业务 Sheet 测试夹具；保护来源测试加入具有有效 `last_import_id` 的可清除 file 对照项。

测试：补充并断言 ZIP 子文件批次错误不调用 merge、成功 commit 后不调用 refresh、真实说明页跳过、错误业务 Sheet 保留 Sheet 诊断并形成 partial、损坏 xlsx 错误与 cleanup。相关三个测试文件共 60 个测试定义。三组 pytest 命令均因 Bundled Python 缺少 `pytest` 阻塞；未安装依赖，未虚报通过。

验证：7 个相关 Python 文件 AST 解析通过；`git diff --check` 通过；暂存区为空；保护哈希保持基线。文件曾被修改。

文件：实际修改或新增白名单文件为 `E:\myfund11111\fund-advisor\backend\services\import_service.py`、`E:\myfund11111\fund-advisor\backend\services\excel_parser.py`、`E:\myfund11111\fund-advisor\backend\schemas\import_result.py`、`E:\myfund11111\fund-advisor\backend\api\imports.py`、`E:\myfund11111\fund-advisor\backend\tests\test_file_import_safety.py` 和 `E:\myfund11111\11_LUNA_HOLDING_CORRECTNESS_STAGE_C.md`。

外部状态：未操作 GitHub、服务器、staging、生产、数据库、OpenClaw、cron 或 systemd；未暂存、提交或推送。

下一步：等待 Sol 最终验收，不进入前端、不暂存、不提交、不推送。

## 8. Sol 第一次验收与最小返修

> 验收日期：2026-09-05
> 结论：生产实现方向正确，但当前测试与实现存在确定性不一致，且关键事务、安全和清理不变量尚未被证明，Stage C 暂不通过。

已确认方向正确：

- ZIP 子文件已改为先解析后整批调用一次 `_import_parsed_batch`，不再逐文件提交和互相清仓。
- `allow_clear=not errors` 已建立 partial 不自动清除门。
- 上传改为流式 20 MiB 限制、随机存储名和 finally 清理；ZIP 未使用 `extractall`。
- `.xlsx`、多 Sheet、混合日期、重复键、结果列表默认值和基本 ZIP 路径/大小门禁已实现。
- 修改文件仍在 Stage C 白名单内，暂存区为空，保护哈希和 `git diff --check` 正常。

必须返修：

1. **修复已知必失败测试**：`test_zip_xls_member_is_rejected_without_extractall` 直接调用 `_validate_zip_members` 并期待 `.xls` 异常，但当前方法不检查扩展名。统一实现与测试边界；更建议成员预校验阶段明确拒绝 `.xls`，不要让测试依赖后续循环。
2. **所有不可信文件名进入受控错误路径**：`import_excel` 和 `import_zip` 当前在 `try` 外调用 `_safe_filename`，NUL、空名称等会直接冒泡。重排局部变量和 finally，使清洗失败返回脱敏的 `ImportResult(status="error")`，同时只清理确实创建且位于上传目录内的路径。`import_file` 的未知格式结果也不得回显原始路径式文件名。
3. **事务失败统一 rollback**：`_import_parsed_batch` 的“无日期/无持仓”错误记录提交当前不在 `try/except` 内；把所有数据库 `add/flush/commit/refresh` 纳入一致异常边界。至少保证 commit/flush 失败时调用一次 rollback，且不返回伪成功。不要声称已提交的事务可由后续 refresh 失败回滚；将返回对象构建所需值安排在安全位置。
4. **消除 ZIP 成员覆盖与不稳定处理**：拒绝规范化后重复的成员路径，并考虑 Windows 大小写折叠；解压目标使用本批次内唯一、非用户路径派生的文件名，避免 `A.xlsx`/`a.xlsx`、重复 central-directory 名称或嵌套路径写到同一目标。排序按规范化成员名和原始次序形成确定结果。
5. **补实际解压总量限制**：`_copy_zip_member` 只检查单成员实际字节。整批复制时累计实际解压字节并执行 100 MiB 上限；不能只信任 central-directory 的 `file_size`。
6. **修复合法零值解析**：`_parse_decimal` 的 `if not value` 会把数值 `0` 当作空。只把 `None` 或空字符串视为空，保证 `0`、`0.0`、`Decimal("0")` 得到 `Decimal("0")`。新增测试，不改变后续业务公式。
7. **收紧工作表识别**：表头校验至少覆盖当前实际读取的 15 列，不能仅前 5 列相同就把任意表当业务表。对于含第 6 行以后业务数据但表头错误的 Sheet，保留带 Sheet 名的 partial 错误；完全空白或只有说明文字的页可跳过。修正多 Sheet 测试，使“说明页”真的没有业务表头，而不是创建一个空业务表。
8. **补齐关键行为测试**：当前 10 个测试不足以支持第 5 节结论。至少新增并实际断言：
   - ZIP 两个有效 xlsx 最终只有一次 merge、一次 commit、同一 import id，组合后的两份持仓同时存在；
   - ZIP 某文件行级错误时合并有效记录但 `allow_clear=False`；批次级日期/冲突错误时 merge 不调用；
   - `_merge_holdings` 只清 file 且 `last_import_id` 非空，manual/quick/legacy 不变；
   - flush/merge/commit 异常触发 rollback；
   - 符号链接、加密、非普通成员、重复/大小写碰撞成员被拒绝；
   - 实际单成员与实际总解压量超限；
   - 空上传、超限上传、重复导入、解析异常和数据库异常后，上传文件及临时目录均不存在；
   - 原始文件名含 Windows/Unix 路径、NUL 或为空时不泄露路径且不产生越界清理。
9. 删除未使用的 `os` 导入，并保持每个新增辅助函数前有简短中文用途说明。

验证仍按第 6 节执行。现有环境不能运行 pytest 时，除 AST、`git diff --check`、哈希检查外，还要用无需第三方导入的静态检查证明测试定义数和测试/实现接口一致；不得再次把未运行的 10 个测试写成覆盖已完成。

只允许修改第 3 节白名单文件，并把返修实际结果追加到本节末尾。不得进入前端、暂存、提交、推送或操作任何外部环境；完成后停止等待 Sol 第二次验收。

## 9. Sol 第二次验收与最终返修

> 验收日期：2026-09-05
> 结论：第 8 节多数问题已修复，但仍有三项确定性语义错误和一项常见输入错误未收口，Stage C 暂不放行。

本轮只修以下项目，不再次大范围重构：

1. **批次级冲突必须整批失败**：`parse_excel` 中的混合业务日期和同唯一键内容冲突都属于批次级校验错误。定义清晰的专用异常类型或等价结构化信号，使独立 Excel 与 ZIP 子文件都能识别；ZIP 不能再只靠匹配“多个业务日期”字符串，也不能把子文件内部的冲突重复键降级为 partial。遇到这两类错误时，`_import_parsed_batch` 和 `_merge_holdings` 均不得调用。
2. **提交点之后不伪装可回滚**：移除成功 `commit` 后的必要 `refresh`，或把返回所需的 id、计数、状态和错误文本在 commit 前保存为局部值，使 commit 成为最后一个可能失败的数据库动作。commit/flush/merge 失败仍必须 rollback；不得在已成功提交后再捕获异常并暗示数据已撤回。无持仓错误记录分支同样先 flush 获取 id、再以 commit 结束。
3. **修正多 Sheet 测试夹具**：当前 `_write_book` 会给“说明”页也写完整业务表头，因此没有验证真正的非业务说明页。测试应显式创建一个仅含说明文字、无业务表头/数据行的 Sheet，再证明它被安全跳过；另加一个“表头错误但第 6 行有业务数据”的 Sheet，证明产生带 Sheet 名的 partial 错误且 `allow_clear=False`。
4. **损坏 xlsx 返回受控错误**：将 openpyxl 读取损坏/伪造 xlsx 的常见异常转换为不包含服务器绝对路径的 `ExcelParseError`，确保上传接口返回 `status=error` 并执行 cleanup，而不是 500。不要捕获 `KeyboardInterrupt`、`SystemExit` 等进程级异常。新增损坏 xlsx 的入口测试。
5. **补漏测试**：明确新增 ZIP 子文件内部冲突导致整批不调用 merge、成功 commit 后不调用 refresh、无数据记录 commit 失败 rollback、真实说明页、错误业务 Sheet partial 禁止 clear、损坏 xlsx 受控错误和 cleanup。现有“保护来源”测试再加入一个可清除的 file+有效 `last_import_id` 对照项，证明不是无条件不清仓。

验收补充证据：Bundled Python 已真实导入 `backend.services.excel_parser` 成功，`_parse_decimal(0)` 返回 `0`；5 个 Stage C 文件 AST 解析通过。完整 pytest 仍因环境缺少 pytest/SQLAlchemy 阻塞。

完成后把实际结果追加到本节末尾并停止。保持第 3 节白名单、保护哈希和全部外部环境边界不变。

## 10. Sol 最终验收发现的运行时名称错误

> 验收日期：2026-09-05
> 结论：仅剩一个确定性阻塞，修复并验证后可完成 Stage C 代码级验收。

`E:\myfund11111\fund-advisor\backend\services\import_service.py` 在 ZIP 解析中写有 `except BatchValidationError:`，但当前导入列表没有导入 `BatchValidationError`。这不会被 AST 检查发现；批次校验异常发生时会在异常匹配阶段触发 `NameError`。

本轮只允许：

1. 从 `backend.services.excel_parser` 显式导入 `BatchValidationError`。
2. 用测试或最小真实导入证明该名称存在，并保留 `test_zip_batch_validation_error_never_calls_merge`。
3. 执行 AST、`git diff --check`、暂存区和保护哈希检查。

不得修改其他实现、进入前端、暂存、提交、推送或操作外部环境。完成后把实际结果追加到本节末尾并停止。

## 10. 第 10 节实际结果（2026-09-05）

结果：完成第 10 节最小名称修复核验并停止。检查发现 `E:\myfund11111\fund-advisor\backend\services\import_service.py` 已显式从 `backend.services.excel_parser` 导入 `BatchValidationError`，本轮无需重复修改其他实现。

验证：无需第三方依赖的 AST 名称检查确认 `BatchValidationError` 导入存在，ZIP 异常处理器引用存在；`test_zip_batch_validation_error_never_calls_merge` 仍保留于 `E:\myfund11111\fund-advisor\backend\tests\test_file_import_safety.py`。相关 AST 解析通过，`git diff --check` 通过。

基线：分支 `codex/holding-ingestion-correctness`；HEAD `6a7744577d76e8ea40fbef7d83700a2c202b815f`；暂存区为空；保护文件 SHA256 未变：`test_position.py`=`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`，`test_screener.py`=`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`。

外部状态：未操作 GitHub、服务器、staging、生产、数据库、OpenClaw、cron 或 systemd；未暂存、提交或推送。

下一步：等待 Sol 最终验收，不进入下一阶段。

## 11. Sol 最终验收结论

> 验收日期：2026-09-05
> 结论：Stage C 通过代码级验收，可以进入独立的前端/API 交互阶段；依赖完整环境中的 pytest 仍是发布前门禁。

验收依据：

- 独立 Excel 和 ZIP 都在完整解析与全局校验后只建立一个导入记录、调用一次 merge 并以一次 commit 结束。
- partial 批次禁止自动清除；混合日期和冲突重复键作为结构化批次错误在 merge 前整批拒绝。
- 文件快照只允许清除 file 且具有有效 `last_import_id` 的持仓，manual、quick、legacy 保持不变。
- `.xls` 已明确拒绝；多 Sheet、零值、重复键、损坏 xlsx、ZIP 路径/成员/大小/碰撞和所有临时清理路径均已实现对应门禁。
- 20 个 Stage C 测试与 A/B 测试合计 60 个测试定义；Bundled Python 缺少 pytest/SQLAlchemy，故没有宣称运行通过。
- `backend.services.excel_parser` 已真实导入，`_parse_decimal(0)` 返回 `0`；Stage C AST 与 `BatchValidationError` 显式导入检查通过。
- `git diff --check` 通过，暂存区为空，两个保护文件哈希保持基线；未操作外部环境。

剩余门禁：在依赖完整的隔离环境运行全部定向/全量测试；本结论不授权暂存、提交、推送、迁移或部署。

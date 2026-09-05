# Luna 持仓正确性修复阶段 A 续跑令

> 编写日期：2026-09-04
> 仓库：`E:\myfund11111`
> 上位执行令：`07_LUNA_HOLDING_INGESTION_CORRECTNESS.md`
> 状态：旧 Luna 执行中途结束并留下未提交半成品；本文件用于全新 Luna 任务短程接续

## 1. 本阶段唯一目标

只完成以下后端闭环并停止：

1. 未知基金按需取得公开基金名称、最新净值和净值日期后再写入。
2. 获取失败时不残留基金、持仓或伪正常零份额记录。
3. 快捷导入使用稳定的“平台 + 基金代码”身份；同基金不同平台不合并。
4. 用户未提供成本时 `cost_nav` 保持未知，不能用最新净值伪造成本。
5. 快捷导入批次具有明确的逐条事务和回滚边界；单条失败不能污染后续记录。
6. `Fund` 是名称与最新净值的规范来源，持仓响应不再优先展示过期副本名称。
7. NAV 刷新取得有效净值后，补齐占位名称；遗留“零份额 + 正市值”记录必须先保留原市值，再按净值反算份额。
8. `share_date` 每次创建请求时计算。
9. 用虚构数据补齐本阶段定向回归测试。

本阶段不处理 Excel/ZIP、账本、迁移、前端和文档总收口；它们分别留给后续短阶段。

## 2. 开始基线

- 当前分支：`codex/holding-ingestion-correctness`。
- 当前 `HEAD`：`6a7744577d76e8ea40fbef7d83700a2c202b815f`。
- 暂存区必须为空。
- 不得清理、还原、stash 或覆盖任何现有差异。
- 当前半成品涉及：
  - `fund-advisor/backend/schemas/holding.py`
  - `fund-advisor/backend/services/holding_service.py`
  - `fund-advisor/backend/services/nav_fetcher.py`
  - `fund-advisor/backend/services/nav_service.py`
  - `fund-advisor/backend/tests/test_holding_ingestion_correctness.py`
- `fund-advisor/backend/services/import_service.py` 和
  `fund-advisor/backend/services/excel_parser.py` 也有同一任务的半成品差异，阶段 A 只保留，不继续修改。

两个仍受保护文件的开始 SHA256：

- `fund-analyzer/tests/test_position.py`：`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`
- `fund-analyzer/tests/test_screener.py`：`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`

若分支、HEAD、暂存区或保护哈希不符，立即停止，不写文件。

## 3. 本阶段允许修改

- `fund-advisor/backend/schemas/holding.py`
- `fund-advisor/backend/services/holding_service.py`
- `fund-advisor/backend/services/nav_fetcher.py`
- `fund-advisor/backend/services/nav_service.py`
- `fund-advisor/backend/tests/test_holding_ingestion_correctness.py`
- 本阶段确需新增的 `fund-advisor/backend/tests/` 虚构数据测试文件
- 本文件中仅允许追加阶段 A 实际结果

除此之外，本阶段全部只读。特别禁止编辑：

- `fund-advisor/backend/services/import_service.py`
- `fund-advisor/backend/services/excel_parser.py`
- `fund-analyzer/tests/test_position.py`
- `fund-analyzer/tests/test_screener.py`

## 4. 对当前半成品的必修检查

1. 删除 `holding_service.py` 中 `locals().get(...)` 的隐式状态处理，明确初始化 `nav` 和 `nav_date`。
2. 不能只在本地不存在 `Fund` 时获取信息；已有占位名称、缺净值或无效净值也要进入安全补全流程。
3. `fetch_fund_info` 必须可 mock，明确超时，校验基金代码、名称、净值和时间戳；不记录外部响应全文。
4. `_to_response` 在关联 `Fund` 存在时使用其名称；仅无关联基金时才兼容持仓副本。
5. `_simple_import_one` 不自行 `commit`；由调用层为每条记录建立提交或回滚边界。失败后必须 `rollback`，成功后结果可刷新。
6. 公开信息失败、数据库 flush/commit 失败和后续记录继续执行都要有测试。
7. 对遗留零份额记录，只有 `shares == 0`、历史 `market_value > 0` 且新净值有效时才反算；先保存原市值，避免现有重算逻辑把它覆盖为零。
8. 不在本阶段新增数据库字段，不伪造导入记录或账本事件。

## 5. 最低定向测试

至少覆盖：

- 未知基金补全成功后名称、净值、日期、份额正确。
- 外部信息失败后数据库无残留。
- 已有占位基金可被补全。
- 同基金不同平台形成不同持仓身份。
- 未提供成本时 `cost_nav is None`。
- 批次中第一条数据库失败后执行回滚，后一条仍能成功。
- 响应优先显示 `Fund.fund_name`。
- 遗留零份额修复保留原市值并正确反算份额。
- 无有效净值时遗留记录保持原样。
- `share_date` 使用 `default_factory`。

测试只能使用虚构数据和临时目录，不连接服务器数据库。

已知本机测试入口现状：

- 系统 `python -m pytest ...` 曾无输出退出 1。
- Codex 捆绑 Python目前没有 `pytest` 模块。

新 Luna 可以先寻找仓库已有且不需安装依赖的可用测试环境；不得安装依赖或连接服务器。若仍无 pytest，执行可用的语法/导入检查并原样报告第一个环境阻塞，不得宣称定向测试通过。

## 6. 禁止事项

- 不暂存、不提交、不推送。
- 不操作 GitHub、服务器 staging、生产、数据库、容器、OpenClaw、cron 或 systemd。
- 不读取或输出真实持仓、凭据、环境值和完整日志。
- 不调整策略参数，不修改 P0，不进入 `fund-analyzer` 业务逻辑。
- 不继续本文件之外的阶段 B、C 或 D。

## 7. 完成格式

完成后必须输出并停止：

```text
结果：完成 / 停止 / 需要确认
基线：分支、HEAD、暂存区
保护：两个文件的结束 SHA256，是否与开始一致
写入：本阶段实际修改和新增文件
正确性：第 1 节九项逐条结论
验收：实际执行的命令、通过数或第一个环境阻塞
保留：import_service/excel_parser 半成品是否未再修改
外部状态：明确写未操作 GitHub、服务器、staging、生产、数据库和 OpenClaw
下一步：等待 Sol 只读审查，不自行继续
```

## 8. Sol 第一次只读验收与返修要求

> 验收时间：2026-09-04
> 结论：阶段 A 已有实质实现，但未通过验收；只返修本节，不扩大范围。

已通过：

- `holding_service.py` 已删除 `locals().get(...)`。
- `Fund` 名称已用于持仓响应。
- 快捷导入不再用最新净值伪造 `cost_nav`。
- 平台已参与快捷持仓身份。
- `_simple_import_one` 已移除内部提交，调用层已有提交和回滚动作。
- `share_date` 已改为 `default_factory`。
- 本阶段五个 Python 文件均通过只读 AST 语法解析。
- 两个受保护测试文件哈希与第 2 节一致，暂存区为空。

必须返修：

1. `_is_placeholder_fund` 必须识别历史真实占位格式 `基金{fund_code}`；当前只识别空值、代码本身、`未知基金` 和 `待补全`，会漏掉用户实际遇到的数据。
2. 当前 `NavService._repair_placeholder_holdings` 只把 `fund.fund_name` 复制到持仓，但普通 NAV 刷新拿到的 `NavData` 不含名称，也没有调用基金信息补全，因此无法把 `基金{fund_code}` 真正改成公开名称。应仅对占位或空名称调用可 mock 的基金信息获取，成功后先更新 `Fund` 名称与有效净值，再修复活动持仓；失败时保持原记录和原市值，不制造半更新。
3. `_repair_placeholder_holdings` 查询应限定活动持仓，避免修改历史已清仓记录，除非现有业务有明确相反证据并补测试。
4. `test_simple_import_rolls_back_failed_record_and_continues` 当前并未模拟“第一条 commit 失败、第二条成功”：第一条在 `_simple_import_one` 就抛错，第二条才触发被设计为失败的第一次 commit，预期 `success == 1` 与测试流程矛盾。改成真实验证第一次提交失败后回滚、第二次提交成功，或明确验证处理阶段失败后的继续执行，测试名称、夹具和断言必须一致。
5. 补齐本文件第 5 节尚缺测试：已有 `Fund` 为 `基金{code}` 时成功补全；已有 Fund 缺净值时补全；NAV 信息获取失败时零份额和正市值完全不变；同代码不同平台不合并；公开响应异常值被拒绝。
6. 回归测试中的假 Session 必须模拟当前代码真实查询和事务顺序，不能因宽松的 `StopIteration -> None` 掩盖多余查询或错误事务。

验收环境事实：

- 系统 `python -m pytest ...` 无输出退出 1。
- Codex 捆绑 Python可运行，但未安装 `pytest`。
- 本轮只读 AST 解析结果为 `AST_PARSE=OK`，这不是 pytest 通过证明。

返修完成后按第 7 节格式汇报；仍不得进入 Excel/ZIP、账本、迁移、前端、提交、推送或服务器阶段。

## 9. Sol 第二次只读验收结论

> 验收时间：2026-09-04
> 结论：阶段 A 代码验收通过；运行验收因本机无 pytest 暂挂，必须在后续隔离 staging 总门禁补跑。

- 已识别 `基金{fund_code}` 历史占位格式。
- 占位 Fund 在 NAV 更新路径会先获取公开名称与有效净值；失败保持原记录不变。
- 只修复活动持仓，清仓历史记录不被改写。
- 回滚测试已改成第一次提交失败、回滚后第二次提交成功。
- 已补占位基金、同基金不同平台、失败保持原值和异常公开响应测试。
- 五个阶段 A Python 文件 AST 解析通过，`git diff --check` 通过。
- 两个受保护测试文件 SHA256 与第 2 节一致，暂存区为空。
- 未操作 GitHub、服务器、staging、生产、数据库、容器或 OpenClaw。

阶段 A 不再继续修改。后续运行总验收若发现失败，必须回到对应短阶段修复，不得用 staging 手工改数据绕过。

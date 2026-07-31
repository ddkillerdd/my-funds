# RFC-011 持仓操作记录（增仓/减仓/清仓）功能

> 状态：**提议（待审阅）** · 日期：2026-07-31 · 目标版本：v6.1
> 所属仓库：my-funds / fund-advisor

## 1. 背景与问题

系统当前**只知道"导入时的持仓快照"，不知道用户之后实际进行的加仓/减仓操作**。

经核实（2026-07-31）：

- 数据库已有 `holding_changes` 表（持仓变动记录），字段齐全，但 **0 条记录**，无人写入。
- 后端 API 只有「新增持仓 / 删除持仓 / 改成本 / 快捷导入」，**没有「记录增仓/减仓」接口**。
- 前端持仓页**没有操作入口**。

### 后果（用户已正确指出）

分析引擎 `advisor_service._load_holdings_from_db()` **每次运行时实时读取 `fund_holdings`（status=1 的活跃持仓）**，并基于份额计算：

- `current_mv = shares × latest_nav`（当前市值）
- `mv_ratio = current_mv / 总市值`（**权重占比 → 直接影响「集中度风险」诊断**）
- `cost = shares × cost_nav`（成本 → 浮盈浮亏、收益率）

**因此：用户实际加/减仓后如果不更新持仓，分析会用过期份额计算权重与收益，建议必然跑偏。**

### 链路验证（已确认，非假设）

```
fund_holdings.shares(改) → advisor_service._load_holdings_from_db() 实时读
 → current_mv / mv_ratio / cost 全变 → QuantIndicators → 组合诊断 → 建议
```

改份额 → 权重/收益/集中度 → 分析结果，**传导是真实的**。

## 2. 目标

给系统加一个「记录我的增仓/减仓/清仓操作」功能，一石三鸟：

1. **分析永远基于最新真实持仓**（改份额 → 下次分析自动用新数据）。
2. **留一份完整的操作历史**（`holding_changes`），可回看"何时、对哪只、加了/减了多少"。
3. 为将来的「**建议后收益跟踪/回测**」打地基（操作记录 + 净值快照）。

## 3. 方案设计（最小改动，不动架构）

### 3.1 用户操作流（你刚才确认的形式）

```
持仓页点「加仓 / 减仓」
  → 选持仓 + 填份额变动(或金额→自动换算份额)
  → 后端 PATCH 当前份额 + 写一条 holding_changes
  → 最新持仓立即生效
  → 下次分析基于它
  → 操作记录累积可回看
```

### 3.2 后端

**新接口**：`POST /api/holdings/{holding_id}/change`

请求体（**金额输入，非份额**）：

```json
{
  "change_type": "increase | decrease",   // 必填：加仓/减仓
  "amount": 10.00,                        // 必填：本次操作的人民币金额（元）
  "cost_nav_input": null,                 // 可选：加仓时的实际买入单价；不填则用最新净值
  "note": "手动加仓10元"                   // 可选：备注
}
```

**金额→份额换算**：`shares_delta = amount / nav`（nav = `cost_nav_input` 或最新净值）。

**Service 逻辑**（`holding_service.py` 新增 `record_change()`，为盈利计算精确服务）：

1. 读当前 `fund_holdings`，校验 `change_type`、`amount > 0`。
2. 取操作净值 `nav`（`cost_nav_input` 或最新净值），算 `shares_delta = amount / nav`。
3. **`increase` 加仓（重算平均成本，B 方案——精确）**：
   - `new_total_cost = 旧成本总价 + amount`（`旧成本总价 = 旧shares × 旧cost_nav`）
   - `new_shares = 旧shares + shares_delta`
   - `新 cost_nav = new_total_cost / new_shares`（**平均成本价被真实拉高/拉低**）
   - → 浮盈浮亏从此准确，不会被加仓次数搞乱
4. **`decrease` 减仓（成本价不变）**：
   - `new_shares = 旧shares − shares_delta`
   - `cost_nav` 保持**不变**（减仓不改变剩余份额的平均成本，数学上正确）
   - 若 `new_shares <= 0` → **清仓**（见 3.4）
5. 更新：`shares`、`market_value = new_shares × nav`、`cost_nav`（仅加仓时）。
6. **写一条 `holding_changes`**（含 shares_before/after、shares_delta、nav_at_change、mv_before/after、amount）。
7. 返回更新后的 `HoldingResponse`。

> **成本价机制（回答为何要重算）**：`cost_nav` 决定浮盈浮亏 `(净值−成本)×份额`。加仓不重算会虚高浮盈；减仓时成本价本就不该变。用户实际填人民币金额 → 加仓重算平均成本最精确，为盈利统计服务。

### 3.3 前端

- **持仓页（HoldingsView）每行加「加仓 / 减仓」两个按钮**。
- 弹小表单：选操作类型 + **填人民币金额（元）** + 可选填"本次买入单价"（不填默认用最新净值）+ 可选备注。
- **实时预览**：填金额后显示"预计新增 X 份 / 新平均成本价 Y"，让用户看到换算结果。
- 提交成功后刷新列表 + 提示"持仓已更新，下次分析将基于最新份额"。

### 3.4 关键决策：减仓到 0 = 清仓

- `decrease` 后 `shares <= 0` → **`status` 置 0（软删/清仓）**，标记该持仓结束。
- `holding_changes` 记 `change_type = "clear"` 一条，`shares_after = 0`。
- 已清仓的基金**不再进入分析**（引擎只读 `status==1`），符合直觉。
- 前端该持仓移出"当前持仓"，但**操作历史里可回看"何时清仓"**。

> 若不想要"自动清仓"，可改为"份额下限=0 仍保留占位"，但会污染组合权重。**默认采纳自动清仓**，如有异议请提。

### 3.5 边界与校验

| 场景 | 处理 |
|------|------|
| `shares_delta <= 0` | 400 拒绝（不允许 0/负变动）|
| increase 后份额异常大 | 不设为上限（真实场景允许）|
| 找不到 holding / 已 status=0 | 404 |
| nav_at_change 不填 | 自动取最新净值 |

## 4. 对分析结果的影响（回答用户疑问）

**会，而且是正向的、必需的。** 加/减仓后：

| 分析维度 | 影响 |
|---------|------|
| 持仓权重 `mv_ratio` | ✅ 更新 → **集中度风险诊断**更真实 |
| 浮盈浮亏 / 收益率 | ✅ 更新（成本×份额）→ **盈亏统计**更真实 |
| 组合总市值 | ✅ 更新 → 总评不再"建仓初期/高集中度"误判 |
| 每只基金技术因子 | 不直接变（基于净值，与份额无关）|
| 动作建议 | 基于新权重重新综合 → **更贴合你实际仓位** |

> ⚠️ 边界说明：技术面因子（Sharpe/回撤/MACD）只依赖**净值序列**，与你增减仓无关——这部分不会因操作改变。改变的是**权重、市值、集中度、盈亏**这些"组合层"维度。

## 5. 测试计划

- 单测：`record_change` 的 increase / decrease / 清仓 / 非法参数。
- 集成：mock 后验证 `holding_changes` 落库行数 + 字段正确。
- 端到端：POST 变更 → GET 持仓份额已变 → 触发 analyze → 报告权重反映了新份额。
- 前端：操作后列表刷新、清仓后移出当前持仓。

## 6. 实施范围与文件

| 层 | 文件 |
|----|------|
| schema | `backend/schemas/holding.py`（新增 `HoldingChangeRequest`）|
| service | `backend/services/holding_service.py`（新增 `record_change`）|
| api | `backend/api/holdings.py`（新增路由 `POST /{id}/change`）|
| 前端 | `frontend/src/views/HoldingsView.vue` + `frontend/src/api/index.js` |

**不动**：分析引擎、数据库表结构（`holding_changes` 已就绪）、择时/荐基引擎。

## 7. 验收标准

1. 加仓后：`fund_holdings.shares` 增加，`holding_changes` 多 1 条 `increase`。
2. 减仓到 0：持仓 `status=0`（清仓），不再进分析，`holding_changes` 记 `clear`。
3. 分析引擎读到的 `mv_ratio` 反映最新份额。
4. 前端"当前持仓"列表 + 操作历史可查。
5. 全项目测试保持通过。

## 8. 决策点（已确认）

1. ✅ **减仓到 0 = 自动清仓**（`status=0`，不再进分析，历史留档）
2. ✅ **按实际人民币金额输入**（如加仓 10 元）；金额→份额按净值换算；前端可选填买入单价
3. ✅ **加仓重算平均成本（B 方案，为盈利精确服务）**：加仓时 `新成本价=(旧成本总价+金额)/新份额`；减仓时成本价不变。浮盈浮亏从此真实

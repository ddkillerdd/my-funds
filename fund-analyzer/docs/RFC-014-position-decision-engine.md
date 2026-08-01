# RFC-014 盈利导向决策引擎 v2（Signal→Position→Risk 三层闭环）

- **状态**: 已批准实现
- **版本**: 1.0.0
- **日期**: 2026-08-01
- **作者**: AAA (代理) / qiqi (负责人)
- **关联代码**: `fund-analyzer/engine/decision.py`, `fund-analyzer/engine/analyzer.py`, `fund-analyzer/engine/models.py`, `fund-advisor/backend/services/advisor_service.py`, `fund-advisor/frontend/src/views/AdvisorView.vue`
- **唯一目标**: **为盈利服务**。所有冗余、不确定、对盈利无直接贡献的功能一律砍掉；所有决策必须可回测、确定性、幂等。

---

## 1. 背景与问题陈述

### 1.1 现状缺陷（基于当前真实代码核对）

现有决策引擎 `decision.py::deterministic_action` 输出**定性四档动作 + 加减百分比 change_pct**，但存在结构性短板：

| # | 缺陷 | 具体表现 | 对盈利的影响 |
|---|------|---------|-------------|
| D1 | **无目标仓位%** | `deterministic_action` 返回 `target_ratio_pct: None`，只有 `change_pct`（相对加/减10%、20%） | 无法回答"这只基金该买/卖到几成"，仓位决策是空的 |
| D2 | **无波动率目标** | 588760 年化波动 78% 仍维持 50% 权重（`change_pct=0` 时不动） | 高波动标的权重未按风险压缩，回撤风险裸奔 |
| D3 | **无回撤硬止损** | 仅 `cur_dd > 30` 触发 sell，没有"从高点连续回撤达阈值强制降仓"的连续机制 | 下跌趋势中减仓不果断，亏损扩大 |
| D4 | **动作口径混乱** | `actions`(rebalance 覆盖) vs `holdings_health[].suggestion`(per-fund) 两套并存且互相矛盾 | 用户收到互相冲突的操作建议 |
| D5 | **LLM 参与动作边缘路径** | 极端降级时 debate 缺失导致动作可能空白；LLM 噪声影响解释 | 不稳定、不可复现 |
| D6 | **无换手成本意识** | 动作阈值无最小间隔/触发带，可能在震荡市频繁小幅调仓 | 手续费吃掉利润（ETF 轮动实证：周期越短净收益越差） |

### 1.2 核心矛盾根源（必须根治）

所有"动作矛盾"的**唯一根源**在 `advisor_service.py` 的动作提取逻辑：它把**组合层 `rebalance_suggestions` 无条件当顶层 `actions` 的优先来源**，覆盖了 per-fund 的 `debate_summary.action`。

**修复原则（本 RFC 根性原则）**：
> **动作权威只能有一个来源：per-fund 的决策引擎输出。组合层（rebalance）只能作为"组合诊断参考"，绝不产生或覆盖操作动作。**

---

## 2. 设计目标（优先级序）

1. **P0 盈利**：决策必须可回测、有实证依据、可复现。
2. **P0 单一权威**：动作只有一套结构、一个来源、一个消费方。
3. **P1 确定性**：同一输入 → 同一输出（纯函数、零随机）。
4. **P1 风控优先**：回撤/波动控制优先级高于收益追求（活得久才赚得多）。
5. **P2 前后端对齐**：后端生成什么，前端呈现什么；字段名统一。
6. **P2 兼容迁移**：历史报告（id≤26）不缺字段也能正常显示，不报错。

---

## 3. 新决策引擎：Signal→Position→Risk 三层闭环

```
┌──────────────────────────────────────────────┐
│  L0 数据层（不变）：QuantIndicators(qi)       │
│     trend / risk(vol,dd) / efficiency(sharpe) │
│     momentum(rsi) / macd / 均线                │
└─────────────────────┬────────────────────────┘
                      ▼
┌──────────────────────────────────────────────┐
│  L1 方向信号层（每基）                          │
│   direction = f(regime, momentum_12m, ma_aln)  │
│   输出：bull/bear/sideways + 方向强度           │
└─────────────────────┬────────────────────────┘
                      ▼
┌──────────────────────────────────────────────┐
│  L2 仓位映射层（每基，波动率目标）               │
│   base_weight（按方向）→ 波动率目标修正          │
│   target_weight = base × (target_vol ÷ vol)    │
└─────────────────────┬────────────────────────┘
                      ▼
┌──────────────────────────────────────────────┐
│  L3 风控层（强制覆盖，优先级最高）               │
│   回撤硬止损 / 波动上限 / 集中度上限 / 熊市防御   │
└─────────────────────┬────────────────────────┘
                      ▼
┌──────────────────────────────────────────────┐
│  动作结构（唯一权威）                            │
│   action + target_weight% + regime + 依据       │
│   decision_source = quant_primary              │
└──────────────────────────────────────────────┘
```

### 3.1 L1 方向信号层（方向）

**输入**：`regime`（沿用 `detect_regime`，市场级）+ 每基 `qi`。

**方向强度 `direction_score ∈ [-1, +1]`**（正值看多，负值看空），取三个子信号加权：

| 子信号 | 计算 | 权重 | 依据 |
|--------|------|------|------|
| `mom` 动量 | `sign(12月收益)`，超基准(MA60)才计正 | 0.50 | TSMOM 在 A 股月超额 0.53% 显著（清华实证）；华泰称 12 月动量最强 |
| `ma` 均线排列 | MA20 vs MA60：黄金/死叉/纠缠 | 0.30 | 趋势跟踪主力信号 |
| `rsi` 技术 | RSI14 偏离 50 的幅度（超买超卖修正） | 0.20 | 辅助，避免追高杀跌 |

```
direction_score = 0.50*mom + 0.30*ma + 0.20*rsi_raw
```

**映射方向**：
- `direction_score > +0.25` → 强方向 `bull-ish`
- `direction_score < -0.25` → 强方向 `bear-ish`
- 其余 → 中性 `neutral`

> **Regime 叠加**：市场级 regime 作为方向可信度调制。`regime=bear` 时，即使个股方向偏多也**下调 base_weight**（熊市防御，见 L2）。

### 3.2 L2 仓位映射层（波动率目标，核心盈利逻辑）

**基准仓位 `base_weight`（按方向）**：

| 方向 | base_weight |
|------|------------|
| bull-ish（强多） | 0.80 |
| neutral（中性/震荡） | 0.50 |
| bear-ish（强空） | 0.25 |

**波动率目标修正**（借鉴 Barroso & Santa-Clara 2015 实证，可提升 Sharpe）：

```
target_weight = clamp( base_weight × (target_vol ÷ realized_vol), 0, 1 )
```
- `target_vol`（目标年化波动率）：**默认 15%**（config 可配，进取 20%，保守 10%）
- `realized_vol`：`qi.risk.annual_volatility_pct / 100`
- `clamp`：`[0.05, 0.95]`（至少保留 5% 观察仓，最多 95% 单基上限由 L3 再压）

**作用示例**：
- 588760：vol=78% > 目标，`target_weight = 0.80 × (0.15/0.78) ≈ 15%` → 从 50% 压到 ~15%
- 蓝筹低波基金：vol=15%，方向中性 → `0.50 × (0.15/0.15) = 50%` → 维持

### 3.3 L3 风控层（强制覆盖，优先级从高到低）

> 风控是**硬约束**，直接覆盖 L2 结果。逐条判定，先命中先生效。

| 优先级 | 风控规则 | 触发 | 强制动作 | target_weight 修正 |
|--------|---------|------|---------|-------------------|
| R1 | **回撤硬止损** | `current_drawdown_pct > 25%` | `sell` | → 0（清仓） |
| R2 | **深回撤重仓止损** | 回撤 15%~25% 且当前权重 > 目标权重×1.5 | `reduce` | → 目标权重×0.5 |
| R3 | **高波动上限** | `annual_vol > 60%` | `reduce` | → min(target, 30%) |
| R4 | **集中度上限** | 单基 target_weight > 50% | `hold` | → 50% |
| R5 | **熊市防御** | `regime=bear` 且 `direction<0` | `reduce` | → min(target, 30%) |
| R6 | **换手阈值**（防摩擦） | `|target - current| < 5pp` | 不动 | 维持 current（避免频繁小幅调仓吃手续费） |

**换手触发带**：只有当 `|target_weight - current_weight| ≥ 5 个百分点` 才产生动作；否则 `hold` 且 target=current。这直接解决 D6（震荡市频繁调仓吃手续费）。

### 3.4 动作输出结构（唯一权威）

每只基金输出**一个权威动作 dict**：

```python
{
    "action": "buy" | "increase" | "hold" | "reduce" | "sell",
    "action_label": "买入/加仓/持有/减仓/卖出",    # 中文标签，后端生成，前端直读
    "current_weight": 0.50,          # 当前权重（十进制）
    "target_weight": 0.15,           # 目标权重（十进制，L2×L3 结果）
    "change_weight_pp": -35.0,       # 变化百分点（target - current）× 100
    "target_weight_pct": 15.0,       # 目标权重%（前端展示用）
    "regime": "bear",                # 市场级 regime
    "direction_score": -0.6,         # L1 方向强度
    "momentum_12m": -18.2,           # 12月动量%
    "vol": 78.0,                     # 年化波动率%
    "max_drawdown": -41.0,           # 历史最大回撤%
    "current_drawdown": -30.5,       # 当前回撤%
    "sharpe": -0.20,                 # Sharpe
    "decision_source": "quant_primary",  # 恒为 quant_primary
    "reason": "波动率78%超标→目标仓位15%（风控R3+R1）",  # 量化生成，非LLM
    "risk_hits": ["R1", "R3"],       # 命中的风控规则（空=无风控触发）
    "friction_held": False,          # 是否因换手阈值而保持不动
}
```

**动作映射（由 target_weight vs current_weight 派生）**：

| 条件 | action | label |
|------|--------|-------|
| target ≈ 0 且 R1 触发 | sell | 卖出 |
| target > current × 1.10 | buy | 买入（新建/重加） |
| target > current（小幅） | increase | 加仓 |
| \|target - current\| 在触发带内 | hold | 持有 |
| target < current（小幅） | reduce | 减仓 |
| target ≈ 0 | sell | 卖出 |

> **关键**：`action` 不是独立判断的，而是从 `target_weight` 与当前重量的**差**推导。**目标仓位是唯一的因，动作是果**。这保证逻辑自洽、可回测。

---

## 4. 数据模型变更（models.py）

### 4.1 新增 `PositionAction` dataclass（唯一动作结构）

```python
@dataclass
class PositionAction:
    action: str = "hold"            # buy/increase/hold/reduce/sell
    action_label: str = "持有"
    current_weight: float = 0.0     # 十进制
    target_weight: float = 0.0      # 十进制
    change_weight_pp: float = 0.0   # 百分点
    target_weight_pct: float = 0.0
    regime: str = "sideways"
    direction_score: float = 0.0
    momentum_12m: float = 0.0
    vol: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    sharpe: float = 0.0
    decision_source: str = "quant_primary"
    reason: str = ""
    risk_hits: List[str] = field(default_factory=list)
    friction_held: bool = False
```

### 4.2 `DebateSummary.action` 迁移

- `DebateSummary.action` 从自由 dict 改为 **存 `PositionAction` 的序列化 dict**（`.to_dict()`）。
- 兼容：读取时若旧 dict 无 `target_weight`，则用 `change_pct` 兜底构造（不 panic）。

### 4.3 `RebalanceSuggestion` 降级为参考

- **保持不变**（字段不动），但从动作提取中**移除**：`_extract_actions` 不再把 `rebalance_suggestions` 当动作来源。
- `portfolio_diagnosis.rebalance_suggestions` 继续存在，只作**组合诊断参考区**展示，标注"组合层面参考，非操作指令"。

---

## 5. 算法实现（decision.py 重写）

### 5.1 新增模块级常量 / 配置

```python
# L2 波动率目标
TARGET_VOL_DEFAULT = 0.15      # 可被 config 覆盖（进取0.20/保守0.10）
# L3 风控阈值
DD_HARD_STOP = 25.0            # 回撤>25% 清仓 (R1)
DD_REDUCE_LO = 15.0            # 回撤15-25% 减仓 (R2)
VOL_HIGH_CAP = 60.0            # vol>60% 压仓 (R3)
CONC_CAP = 0.50                # 单基上限50% (R4)
BEAR_CAP = 0.30                # 熊市防御上限30% (R5)
FRICTION_BAND = 5.0            # 换手触发带5pp (R6)
BASE_WEIGHT = {"bull-ish": 0.80, "neutral": 0.50, "bear-ish": 0.25}
```

### 5.2 新函数签名

```python
def compute_direction(qi, regime: str) -> float:
    """L1: 返回 direction_score ∈ [-1,1]"""

def compute_target_weight(qi, regime: str, direction: float) -> float:
    """L2+L3: 返回经波动率目标修正 + 风控覆盖的 target_weight(十进制)"""

def build_position_action(qi, regime: str, current_weight: float) -> PositionAction:
    """总入口：方向→仓位→风控→动作结构。幂等、零LLM依赖。"""
```

### 5.3 `deterministic_action` 保留兼容

- 保留旧 `deterministic_action` 作为**内部降级兜底**（数据不足时）。
- 主路径改用 `build_position_action`。

### 5.4 `merge_with_llm_explanation` 简化

- 移除 LLM 对动作的任何影响（本来就只有冲突注记）。
- LLM 仅可附加 `interpretation`（可选解读文字），**永不进动作字段**。

---

## 6. 后端映射变更（advisor_service.py）

### 6.1 `_extract_actions` 重写（根治矛盾根源）

**旧逻辑（错误）**：rebalance_suggestions 优先 → per-fund 兜底 → 两套打架。

**新逻辑（单一权威）**：
```python
def _extract_actions(self, report):
    actions = []
    for fd in report.per_fund_diagnosis:
        ds = fd.debate_summary          # 每基决策的唯一来源
        pos = ds.action                 # PositionAction dict
        actions.append({
            "fund_code": fd.fund_code,
            "fund_name": fd.fund_name,
            "action": pos["action"],
            "action_label": pos["action_label"],
            "current_weight": pos["current_weight"],
            "target_weight": pos["target_weight"],
            "target_weight_pct": pos["target_weight_pct"],
            "change_weight_pp": pos["change_weight_pp"],
            "regime": pos["regime"],
            "decision_source": pos["decision_source"],
            "reason": pos["reason"],
            "risk_hits": pos["risk_hits"],
        })
    return actions
```

### 6.2 `holdings_health` 与 `actions` 统一

- `holdings_health[].suggestion` 直接取 `PositionAction.action_label` → **与 `actions[]` 完全一致**（同一来源）。
- 删除两处各自独立拼装的逻辑，统一走 `build_portfolio_actions(report)` 一个函数产出两个视图。

### 6.3 response 顶层补充

- `portfolio_diagnosis.rebalance_suggestions` 保留但不进 actions，前端标注"参考"。
- 新增 `engine.action_schema: "position_v1"` 便于前端识别新结构。

---

## 7. 前端变更（AdvisorView.vue）

### 7.1 统一数据源

- 健康度卡 / 操作建议列表 / 逐基详情 **三个视图全部读 `report.actions[]`**（唯一权威）。
- 移除对 `holdings_health[].suggestion` 和 `per_fund_diagnosis[].debate.summary` 动作的独立读取。

### 7.2 动作标签直读后端

- 不再前端硬编码 `watch→关注`。
- 直接显示 `action_label`（后端返回）。
- `target_weight_pct %` 作为新增列/指标展示。

### 7.3 兼容兜底

- `if !action.target_weight_pct && action.change_pct` → 用 `change_pct`（旧报告）。
- `if !action.action_label` → 用旧映射函数（旧报告）。
- 缺失字段显示 `-`，不报错、不空白。

---

## 8. 回测与验证（为盈利服务的硬闭环）

### 8.1 回测范围

`backtest.py` 扩展：用历史 NAV 跑 **信号→仓位→风控 全流程**，输出：

| 指标 | 含义 |
|------|------|
| 年化收益 CAGR | 策略真实回报 |
| 最大回撤 MaxDD | 最坏回撤 |
| Sharpe（无风险=0） | 风险调整收益 |
| 对数超额 vs 持有不动 | 策略相对"躺平"是否更好 |
| 换手率 / 交易次数 | 成本压力 |
| 命中率（动作后 >0 收益比例） | 决策质量 |

### 8.2 通过标准

- 回测 Sharpe **≥ 持有不动的 Sharpe**（否则无存在价值）
- 最大回撤 **≤ 持有不动的最大回撤**（风控有效）
- 至少 1 项（收益或 Sharpe）显著优于持有不动

---

## 9. 迁移与兼容

| 项 | 处理 |
|----|------|
| 历史报告（id≤26） | 无新字段 → 前端兼容兜底显示，不报错 |
| 落库 schema | `advisor_report.report_json` 宽松 JSON，新字段直接加入，老字段保留 |
| LLM 降级 | 决策全量化，无 LLM 参与动作 → 不再有降级导致动作空白 |
| `deterministic_action` | 保留为兜底函数，不删除（向后兼容测试） |

---

## 10. 测试计划

新增 `tests/test_position.py`：

1. **波动率目标**：vol=78% 基金 → target_weight ≈ 15%（不超 20%）
2. **回撤硬止损**：cur_dd>25% → action=sell, target=0
3. **熊市防御**：bear+方向<0 → target ≤ 30%
4. **集中度上限**：低 vol 基金 target>50% → 被压到 50%
5. **换手触发带**：|target-current|<5pp → hold, friction_held=True
6. **幂等性**：同输入两次调用输出完全一致
7. **零LLM依赖**：无 LLM 调用路径
8. **动作-仓位自洽**：action 与 target/current 关系一致（buy 必 target>current 等）
9. **前后端字段**：`_extract_actions` 输出字段 ⊆ response schema

---

## 11. 验收标准（Done 定义）

- [ ] 决策引擎输出 PositionAction（含 target_weight），全量化、幂等、零 LLM
- [ ] `_extract_actions` 单一权威：actions == holdings_health suggestion == per-fund action
- [ ] rebalance 不再覆盖动作（组合诊断参考区保留）
- [ ] 前端三视图统一读 actions[]，直读 action_label + target_weight_pct
- [ ] 历史报告兼容显示不报错
- [ ] 全部测试通过（新旧）
- [ ] 回测至少 1 项优于持有不动
- [ ] 端到端：触发 run-advisor → 落库 → 前端可见新动作结构

---

## 12. 明确不做（防止范围蔓延）

- ❌ 不改荐基模块（screener/recommend）
- ❌ 不改持仓/净值/邮件模块
- ❌ 不重绘前端界面，仅统一数据源和字段
- ❌ 不引入机器学习模型（当前数据量不足以训练，纯规则+实证阈值更稳）
- ❌ 不新增外部数据源（暂用现有 NAV/指数）

# RFC-006: 分析质量与操作建议强化

> 路径: `fund-analyzer/docs/RFC-006-analysis-quality.md`
> 状态: 待实施
> 优先级: P0（分析质量是产品核心价值）

---

## 一、现状问题全诊断

### 问题 1: 操作建议千人一面

**现状数据**（报告 #18）:

| 基金 | health | Sharpe | 回撤 | action | reasoning |
|------|--------|--------|------|--------|-----------|
| 018044 纳指 | 70 | 1.76 | -3.99% | hold | 趋势向好但整体风险调整后收益一般 |
| 000311 沪深300 | 70 | 0.71 | -2.98% | hold | 趋势向好但性价比一般 |
| 161725 白酒 | 45 | **-0.33** | **-18.10%** | hold | 四位分析师观点分歧较大... |
| 588760 科创 | 70 | -0.20 | -25.86% | hold | 趋势向好但性价比一般 |

**问题**: Sharpe -0.33、回撤 -18% 的白酒仍然建议"持有"——标准太松，没有可操作的差异化。

### 问题 2: 缺少仓位数量建议

**现状**: `DebateSummary.action` 只有 `type/中文reasoning`，不包含目标仓位比例。
**影响**: 用户知道"减仓"但不知道减多少。

### 问题 3: 缺少可量化触发条件

**现状**: "若MACD形成死叉再考虑减仓"——没有具体阈值。
**影响**: 用户需要自己盯盘判断，可操作性差。

### 问题 4: 缺少纵向历史对比

**现状**: `HistoricalComparison` 数据类已定义但 `_build_historical_comparison` 返回空。
**影响**: health_score 60→45 是恶化还是上次偏高？无从判断。

### 问题 5: 缺少市场环境/同类对比

**现状**: `fact_card` 只有基金自身指标，没有大盘或同类基准。
**影响**: "年化波动 42%"——高不高？同类平均多少？无参照系。

### 问题 6: debate 缺少量化决策规则

**现状**: `DEBATE_PROMPT` 只给 `action.type: buy/hold/sell/reduce/add` 枚举，没有决策矩阵。
**影响**: LLM 的判断标准不稳定——有时 Sharpe<0 还给 hold，有时给 reduce。

### 问题 7: risk_score 归一化方向不一致

**现状**: `overall_risk_score` 越高=风险越大（0-100），但 trend/value/tech 越高=越看好。`fallback_debate` 的 health 计算用 `(trend + (100-risk) + value + tech) / 4` 简单平均。
**影响**: 161725 的 risk=78 → risk_norm=22，压低整体 health 到 45。但 risk 高不等于全部否定——可能是高波动高收益型基金。

### 问题 8: fallback_debate 全给 hold

**现状**:
```python
# llm_client.py L447
"action": {"type": "hold", "confidence": 0.5, "reasoning": "降级分析, 建议保守持有"}
```
**影响**: LLM 全挂时 4 只基金全给相同的"保守持有"，包括 Sharpe -0.33 的垃圾基金。

### 问题 9: 组合级 rebalance_suggestions 缺少数量

**现状**: `RebalanceSuggestion` 有 `current_ratio/target_ratio/change_pct` 字段，但 LLM 经常不填或填得不准。
**影响**: 组合建议"减仓白酒"——减到多少？不明确。

### 问题 10: cross_validation 不影响最终输出

**现状**: `_cross_validate` 返回 `CrossValidationResult`，里面可能发现"置信度虚高"，但最终报告的 `confidence` 不受交叉验证结果调整。
**影响**: 交叉验证形同虚设——发现问题但不修正。

---

## 二、解决方案设计

### 方案 A: 量化决策矩阵注入 Debate Prompt（P0）

**目标**: 让 LLM 有明确的、可量化的决策标准，消除"千人一面 hold"。

**改动文件**: `engine/prompts.py` — `DEBATE_PROMPT`

**新增内容**:

在 `DEBATE_PROMPT` 的 JSON Schema 之前插入决策矩阵：

```text
## 操作建议决策表（必须严格参照，不可自行降低标准）

### action.type 决策规则
| 条件 | action | 说明 |
|------|--------|------|
| health≥80 且 Sharpe>1.0 且 trend=up | buy | 基本面/趋势/性价比三优，可新建或大幅增持 |
| health≥65 且 trend=up 且 Sharpe>0.5 | hold | 趋势健康，风险调整收益可接受 |
| health≥65 但 trend=down 或 MACD=death_cross | watch | 仓位不调但需密切监控，附触发条件 |
| health 45-65 且 Sharpe<0.5 | reduce | 风险调整收益差，减仓10-20% |
| health 45-65 且 当前回撤>历史最大回撤的60% | reduce | 回撤接近历史极值，减仓10-20% |
| health<45 | reduce | 综合质量差，减仓20-30% |
| health<30 或 回撤>-30% 或 Sharpe<-0.5 | sell | 极端恶化，清仓或大幅减仓 |

### action.change_pct 仓位调整幅度
| action | change_pct 范围 | 约束 |
|--------|----------------|------|
| buy | +15~25% | 新建仓或大幅增持 |
| add (增持) | +5~15% | 在持有基础上加仓 |
| hold | 0% | 不调整 |
| watch | 0% | 不调整但设触发条件 |
| reduce | -10~25% | 根据恶化程度递增 |
| sell | -50~100% | 大幅减仓或清仓 |

### action.trigger_conditions（必须提供，2-3 个可量化条件）
格式: "指标名 阈值 → 执行操作"
示例:
- "MACD柱 < -0.005 → 转为 reduce"
- "当前回撤 > -15% → 追加减仓5%"
- "RSI < 30 且连续3日 → 触发紧急减仓"
- "Sharpe 连续2月 < 0 → 转为 sell 候选"
```

**修改 DEBATE_PROMPT 的 JSON Schema**:

```json
{
  "action": {
    "type": "hold",
    "confidence": 0.70,
    "reasoning": "趋势向好但性价比一般。建议维持当前仓位。",
    "change_pct": 0,
    "trigger_conditions": [
      "MACD柱 < -0.005 → 转为reduce，减仓10%",
      "当前回撤 > -8% → 追加减仓5%"
    ],
    "target_ratio_pct": null
  }
}
```

**新增字段说明**:
- `change_pct`: 仓位调整百分比（正=加仓，负=减仓，0=不调）
- `trigger_conditions`: 未来触发改仓的量化条件列表
- `target_ratio_pct`: 建议的目标持仓比例（null=不涉及新目标，数字=百分比）

**更新 DebateSummary 数据类** (`engine/models.py`):

```python
@dataclass
class ActionResult:
    """操作建议详情"""
    type: str = "hold"              # buy/add/hold/watch/reduce/sell
    confidence: float = 0.5
    reasoning: str = ""
    change_pct: float = 0.0         # P0 新增: 仓位调整幅度
    trigger_conditions: List[str] = field(default_factory=list)  # P0 新增
    target_ratio_pct: Optional[float] = None  # P0 新增: 目标比例

# DebateSummary.action 从 Dict 改为 ActionResult
@dataclass
class DebateSummary:
    ...
    action: ActionResult = field(default_factory=ActionResult)
    ...
```

**兼容性**: `_report_to_api_json` 里 `ds.action.get("type")` 改为 `ds.action.type`。fallback 函数也返回 `ActionResult` 对象。

---

### 方案 B: 强化 fallback_debate 决策逻辑（P0）

**目标**: LLM 全挂时也能给出有差异化的可操作建议。

**改动文件**: `engine/llm_client.py` — `fallback_debate`

**新逻辑**:

```python
def fallback_debate(qi, trend, risk, value, technical) -> Dict[str, Any]:
    scores = [
        trend.get("overall_trend_score", 50),
        risk.get("overall_risk_score", 50),
        value.get("overall_value_score", 50),
        technical.get("overall_tech_score", 50),
    ]
    risk_norm = 100 - scores[1]
    avg = int((scores[0] + risk_norm + scores[2] + scores[3]) / 4)

    # 读取关键量化指标
    sharpe = qi.efficiency.sharpe_ratio or 0
    sortino = qi.efficiency.sortino_ratio or 0
    current_dd = abs(qi.risk.current_drawdown_pct or 0)
    max_dd = abs(qi.risk.max_drawdown_pct or 0)
    vol = qi.risk.annual_volatility_pct or 0
    macd_signal = qi.macd.signal or "unknown"
    trend_dir = qi.trend.trend_direction or "unknown"

    # 量化决策
    conditions = []
    if avg < 30 or current_dd > 30 or sharpe < -0.5:
        action_type = "sell"
        change = -50 if current_dd > 30 else -30
        reasoning = f"健康分{avg}+回撤{current_dd:.1f}%+Sharpe{sharpe:.2f}触发清仓线"
        conditions.append("净值跌破MA60 → 全部清仓")
    elif avg < 55 or sharpe < 0:
        action_type = "reduce"
        change = -20 if sharpe < 0 else -10
        reasoning = f"Sharpe{sharpe:.2f}偏低，减仓{abs(change)}%控制风险"
        conditions.append(f"MACD柱 < -0.005 → 追加减仓5%")
        conditions.append(f"当前回撤 > -{max_dd*0.6:.0f}% → 转为sell")
    elif avg > 75 and sharpe > 1.0:
        action_type = "add"
        change = 10
        reasoning = f"健康分{avg}+Sharpe{sharpe:.2f}三优信号，建议增持10%"
        conditions.append("Sharpe连续2月>1.5 → 再增持5%")
    elif macd_signal == "death_cross_active" or trend_dir == "down":
        action_type = "watch"
        change = 0
        reasoning = "趋势走弱/MACD死叉，暂持但需监控"
        conditions.append("MACD柱 > 0.005 且持续3日 → 转为hold")
        conditions.append("RSI < 30 → 触发减仓10%")
    else:
        action_type = "hold"
        change = 0
        reasoning = "信号混合，维持当前仓位"
        conditions.append("MACD柱 < -0.005 → 转为reduce")

    # risks/strengths 也用量化指标填充
    risks = []
    if vol > 30:
        risks.append(f"年化波动率{vol:.1f}%属于高风险水平")
    if current_dd > 10:
        risks.append(f"当前回撤{current_dd:.1f}%仍然显著")
    if sharpe < 0.5:
        risks.append(f"Sharpe {sharpe:.2f}低于1.0，风险调整收益不佳")
    if macd_signal == "death_cross_active":
        risks.append("MACD死亡交叉，动能减弱")

    strengths = []
    if sharpe > 1.0:
        strengths.append(f"Sharpe {sharpe:.2f} > 1.0，风险调整收益优秀")
    if sortino > 1.0:
        strengths.append(f"Sortino {sortino:.2f} > 1.0，下行风险控制良好")
    if trend_dir == "up":
        strengths.append("趋势方向向上，均线系统支撑")
    if current_dd < max_dd * 0.5:
        strengths.append(f"当前回撤{current_dd:.1f}%远低于历史最大{max_dd:.1f}%，风险已释放")

    return {
        "contradictions": [],
        "consensus_level": 0.5,
        "consensus_label": "partial_disagreement",
        "health_score": avg,
        "health_label": (
            "良好" if avg >= 70 else "中等偏上" if avg >= 55 else
            "中等" if avg >= 40 else "中等偏下" if avg >= 25 else "较差"
        ),
        "strengths": strengths,
        "risks": risks,
        "action": {
            "type": action_type,
            "confidence": 0.45,
            "reasoning": reasoning,
            "change_pct": change,
            "trigger_conditions": conditions,
            "target_ratio_pct": None,
        },
        "confidence": 0.35,
        "uncertainties": ["LLM调用失败, 使用降级分析(含量化决策)"],
    }
```

**验证**:

| 基金 | Sharpe | 回撤 | fallback action | change |
|------|--------|------|-----------------|--------|
| 018044 | 1.76 | -3.99% | add | +10% |
| 000311 | 0.71 | -2.98% | hold | 0% |
| 161725 | -0.33 | -18.10% | reduce | -20% |
| 588760 | -0.20 | -25.86% | reduce | -20% |

✅ 不再全部 hold，有差异化。

---

### 方案 C: 纵向历史对比（P1）

**目标**: 对比上一期分析，注入 debate prompt，让 LLM 知道趋势变化。

**改动文件**: 
- `engine/analyzer.py` — `_build_historical_comparison` + `_debate_synthesis`
- `engine/prompts.py` — `build_debate_prompt` 增加 `history_context` 参数
- `fund-advisor/backend/services/advisor_service.py` — 传入上一期报告数据

#### C.1: 修复 `_build_historical_comparison`

```python
# analyzer.py
def _build_historical_comparison(
    self,
    current_report: AnalysisReport,
    prev_report_data: Optional[Dict[str, Any]],  # 从 DB 读取的上一期 JSON
) -> HistoricalComparison:
    """对比上一期分析结果。"""
    if not prev_report_data:
        return HistoricalComparison()

    changes = []
    prev_holdings = {
        h["fund_code"]: h
        for h in prev_report_data.get("holdings_health", [])
    }
    current_holdings = {
        fd.fund_code: fd
        for fd in current_report.per_fund_diagnosis
    }

    for code, prev_h in prev_holdings.items():
        curr_fd = current_holdings.get(code)
        if not curr_fd or not curr_fd.debate_summary:
            continue

        prev_health = prev_h.get("health_score", 0)
        curr_health = curr_fd.debate_summary.health_score
        if prev_health != curr_health:
            changes.append(HistoricalChange(
                fund_code=code,
                dimension="health_score",
                previous_value=float(prev_health),
                current_value=float(curr_health),
                delta=f"{'↑' if curr_health > prev_health else '↓'}{abs(curr_health - prev_health)}",
                interpretation=(
                    f"健康分从{prev_health}变至{curr_health}"
                    f"({'改善' if curr_health > prev_health else '恶化'})"
                ),
            ))

        prev_action = prev_h.get("suggestion", "hold")
        curr_action = curr_fd.debate_summary.action.get("type", "hold") if isinstance(curr_fd.debate_summary.action, dict) else curr_fd.debate_summary.action.type
        if prev_action != curr_action:
            changes.append(HistoricalChange(
                fund_code=code,
                dimension="action",
                previous_value=None,
                current_value=None,
                delta=f"{prev_action} → {curr_action}",
                interpretation=f"操作建议从{prev_action}变为{curr_action}",
            ))

    return HistoricalComparison(
        previous_report_id=prev_report_data.get("id"),
        previous_generated_at=prev_report_data.get("generated_at"),
        changes=changes,
        prediction_accuracy=None,
    )
```

#### C.2: 注入 debate prompt

`build_debate_prompt` 新增参数:

```python
def build_debate_prompt(
    qi: QuantIndicators,
    trend: str, risk: str, value: str, technical: str,
    history_context: str = "",  # P1 新增
) -> str:
```

`DEBATE_PROMPT` 模板增加:

```text
{history_section}

## 输出 JSON Schema
...
```

其中 `history_section` 格式:

```text
## 上期分析对比（供参考，判断趋势变化）
基金 161725 上期:
- health_score: 60 → 本期需评估
- action: hold
- 关键风险: "波动率42%"

**注意**: 如果本期 health_score 应明显低于上期，请在 reasoning 中说明恶化原因。
如果本期 action 应比上期更保守（如 hold→reduce），请明确标注变化。
```

#### C.3: advisor_service 传入上一期

```python
# advisor_service.py _analyze_v3
# 取上一期报告
prev_report = self._get_latest_report_json()

# 分析完成后
report = analyzer.analyze(portfolio, prev_report_data=prev_report)
```

`Analyzer.analyze` 增加可选参数:

```python
def analyze(
    self,
    portfolio: PortfolioInput,
    prev_report_data: Optional[Dict[str, Any]] = None,  # P1
) -> AnalysisReport:
    ...
    # 在 debate 之前注入历史
    history_context = self._build_history_text(prev_report_data, portfolio)
    ...
    fd.debate_summary = self._debate_synthesis(
        qi, fd.trend_view, fd.risk_view, fd.value_view, fd.technical_view,
        model_sources=model_sources,
        history_context=history_context,  # P1
    )
```

---

### 方案 D: 同类基准对比（P1）

**目标**: fact_card 中增加"同类排名"和"大盘对比"。

**改动文件**:
- `engine/quant.py` — `compute_all` 增加基准计算
- `engine/prompts.py` — `build_fact_card` 增加基准段落
- `engine/models.py` — `QuantIndicators` 增加 `peer_benchmark` 字段
- `advisor_service.py` — 传入大盘 ETF 净值作为基准

#### D.1: 新增 PeerBenchmark 数据类

```python
# models.py
@dataclass
class PeerBenchmarkData:
    """同类/大盘对比数据"""
    # 大盘对比
    market_annual_volatility: Optional[float] = None   # 大盘年化波动率%
    market_return_6m: Optional[float] = None           # 大盘近6月收益%
    market_current_drawdown: Optional[float] = None     # 大盘当前回撤%
    # 同类排名（如果有数据源）
    peer_sharpe_percentile: Optional[float] = None      # Sharpe在同类中的百分位
    peer_volatility_percentile: Optional[float] = None
    peer_avg_sharpe: Optional[float] = None
    peer_avg_volatility: Optional[float] = None
    notes: List[str] = field(default_factory=list)

# QuantIndicators 增加:
peer_benchmark: Optional[PeerBenchmarkData] = None
```

#### D.2: 基准数据来源

使用沪深 300 ETF (510300) 或中证 500 ETF (510500) 的净值作为大盘基准:

```python
# advisor_service.py _build_portfolio_input
# 抓取 510300 的净值作为 market benchmark
market_navs = self._load_nav_history("510300", limit=252)
portfolio.market_benchmark_navs = market_navs  # PortfolioInput 新增字段
```

```python
# quant.py compute_all
def compute_all(holding: FundHolding, market_navs: Optional[List[NavPoint]] = None) -> QuantIndicators:
    ...
    if market_navs:
        market_arr = np.array([n.nav for n in market_navs])
        market_returns = np.diff(market_arr) / market_arr[:-1]
        peer = PeerBenchmarkData(
            market_annual_volatility=float(np.std(market_returns) * np.sqrt(252) * 100),
            market_return_6m=float((market_arr[-1] / market_arr[-126] - 1) * 100) if len(market_arr) >= 126 else None,
            market_current_drawdown=float((market_arr[-1] / np.max(market_arr) - 1) * 100),
        )
        qi.peer_benchmark = peer
    return qi
```

#### D.3: fact_card 增加基准段落

```python
# prompts.py build_fact_card
if qi.peer_benchmark:
    pb = qi.peer_benchmark
    parts.append("【市场环境对比】")
    parts.append(f"大盘年化波动率: {v(pb.market_annual_volatility, '%')}")
    parts.append(f"大盘近6月收益: {v(pb.market_return_6m, '%')}")
    parts.append(f"大盘当前回撤: {v(pb.market_current_drawdown, '%')}")
    if pb.peer_avg_sharpe is not None:
        parts.append(f"同类平均Sharpe: {v(pb.peer_avg_sharpe)} vs 本基金: {v(qi.efficiency.sharpe_ratio)}")
    if pb.peer_avg_volatility is not None:
        parts.append(f"同类平均波动率: {v(pb.peer_avg_volatility, '%')} vs 本基金: {v(qi.risk.annual_volatility_pct, '%')}")
    # 量化对比结论
    if pb.market_annual_volatility and qi.risk.annual_volatility_pct:
        ratio = qi.risk.annual_volatility_pct / pb.market_annual_volatility
        parts.append(f"波动率/大盘: {ratio:.2f}x ({'远高于' if ratio > 2 else '高于' if ratio > 1.3 else '接近' if ratio > 0.8 else '低于'})")
    parts.append("")
```

---

### 方案 E: 交叉验证结果回写置信度（P0）

**目标**: cross_validation 发现的置信度虚高要实际调整最终 confidence。

**改动文件**: `engine/analyzer.py` — `analyze` 末尾

**现状**:
```python
# analyzer.py L770
report.cross_validation = self._cross_validate(report_text, all_facts)
# 然后就没了——cv 结果不影响 report
```

**修改**:

```python
report.cross_validation = self._cross_validate(report_text, all_facts)

# P0: 交叉验证结果回写 confidence
if report.cross_validation:
    cv = report.cross_validation
    if cv.adjusted_overall_confidence is not None:
        original = report.confidence.overall
        adjusted = cv.adjusted_overall_confidence
        report.confidence.overall = adjusted
        # 重新计算 label
        report.confidence.overall_label = (
            "高" if adjusted >= 0.75 else
            "中高" if adjusted >= 0.60 else
            "中等" if adjusted >= 0.45 else
            "中低" if adjusted >= 0.30 else
            "低"
        )
        report.confidence.warnings.extend(cv.warnings)
        # 逐基金回写
        for issue in cv.issues:
            if issue.get("severity") == "major":
                report.confidence.overall = min(report.confidence.overall, 0.5)
```

---

### 方案 F: 增强组合级调仓建议（P1）

**目标**: `rebalance_suggestions` 必须包含 target_ratio 和量化回测验证。

**改动文件**: `engine/prompts.py` — `PORTFOLIO_PROMPT`

在 PORTFOLIO_PROMPT 中加入约束:

```text
## 调仓建议严格要求
- 每条 rebalance_suggestions 必须包含:
  - current_ratio: 当前占比（从输入数据获取）
  - target_ratio: 目标占比（必须给出具体数字）
  - change_pct: 变化幅度 = (target - current) / current * 100
  - reason: 量化依据（引用有效前沿分析或相关性数据）
  - evidence: 支撑数据的列表
- 只对非货币基金提出调仓建议
- 如果组合已在有效前沿附近（distance < 1%），可返回空列表
- 调仓幅度不超过 ±25%（单次建议不超过25%变动）
```

---

### 方案 G: 增强 Debate Prompt 的 risk 归一化逻辑（P2）

**目标**: health_score 计算不再简单平均 4 个 score，而是加权。

**在 DEBATE_PROMPT 中增加指导**:

```text
## health_score 计算引导（不要简单平均4个视角）
- trend_score 权重 25%: 趋势是短期价格走向
- risk_inverse 权重 30%: 风险是最重要维度（1 - risk_score/100）
- value_score 权重 25%: 性价比决定中期持有价值
- tech_score 权重 20%: 技术面是短期辅助信号
- 如果 Sharpe < 0，health_score 上限不超过 55（不管其他指标多好）
- 如果当前回撤 > 历史最大回撤 80%，health_score 上限不超过 50
```

---

## 三、实施计划

### 分批实施

| 批次 | 方案 | 改动文件 | 工作量 | 预期收益 |
|------|------|---------|--------|---------|
| **Batch 1 (P0)** | A. 决策矩阵 | prompts.py, models.py | 2h | 操作建议从"全hold"变成有区分度 |
| **Batch 1 (P0)** | B. fallback强化 | llm_client.py | 1h | LLM全挂也有差异化建议 |
| **Batch 1 (P0)** | E. 交叉验证回写 | analyzer.py | 0.5h | 置信度不再虚高 |
| **Batch 2 (P1)** | C. 纵向对比 | analyzer.py, prompts.py, advisor_service.py | 3h | 能看到变化趋势 |
| **Batch 2 (P1)** | D. 同类基准 | quant.py, prompts.py, models.py, advisor_service.py | 3h | 有市场参照系 |
| **Batch 2 (P1)** | F. 组合建议增强 | prompts.py | 0.5h | 调仓建议有具体数量 |
| **Batch 3 (P2)** | G. 归一化权重 | prompts.py | 0.5h | health_score 更合理 |

### 执行顺序

1. models.py: 新增 `ActionResult` 数据类，`DebateSummary.action` 改类型
2. llm_client.py: 重写 `fallback_debate`，返回含 change_pct/trigger_conditions
3. prompts.py: DEBATE_PROMPT 注入决策矩阵 + JSON schema 更新
4. analyzer.py: `_debate_synthesis` 解析新字段 + 交叉验证回写
5. advisor_service.py: `_report_to_api_json` 导出新字段
6. AdvisorView.vue: 前端显示 change_pct 和 trigger_conditions
7. 测试: 单元测试 + 生产验收

### 文件影响图

```
models.py
  ├── ActionResult (新增)
  ├── DebateSummary.action: Dict → ActionResult
  └── PeerBenchmarkData (新增, P1)

llm_client.py
  ├── fallback_debate: 全重写
  └── parse_json_response: 适配 ActionResult

prompts.py
  ├── DEBATE_PROMPT: 注入决策矩阵 + history_context + 归一化引导
  ├── build_debate_prompt: 新增 history_context 参数
  ├── PORTFOLIO_PROMPT: 增强调仓约束
  └── build_fact_card: 增加市场环境对比段落 (P1)

analyzer.py
  ├── _debate_synthesis: 解析 ActionResult 新字段
  ├── _build_historical_comparison: 实现历史对比 (P1)
  ├── analyze(): 交叉验证结果回写 confidence
  └── analyze(): 接受 prev_report_data 参数 (P1)

advisor_service.py
  ├── _analyze_v3: 传入上一期报告 + 市场基准净值
  └── _report_to_api_json: 导出 change_pct/trigger_conditions/target_ratio

AdvisorView.vue
  └── 操作建议卡片: 显示 change_pct + trigger_conditions
```

---

## 四、验收标准

### Batch 1 (P0) 验收

| 测试项 | 期望 |
|--------|------|
| 161725 白酒 (Sharpe -0.33) | action=reduce, change_pct=-15~-20% |
| 588760 科创 (Sharpe -0.20, DD -25.86%) | action=reduce, change_pct=-10~-20% |
| 018044 纳指 (Sharpe 1.76) | action=hold 或 add |
| 000311 沪深300 (Sharpe 0.71) | action=hold |
| fallback_debate (全LLM挂) | 161725 → reduce, 018044 → add/hold |
| 每条 action 有 ≥2 trigger_conditions | ✅ |
| 交叉验证发现 major issue 时 | confidence 降到 ≤0.5 |

### Batch 2 (P1) 验收

| 测试项 | 期望 |
|--------|------|
| 上期 health=60 本期=45 | debate reasoning 提及恶化 |
| 操作建议从 hold→reduce | HistoricalChange 记录 |
| fact_card 有"市场环境对比"段 | 包含大盘波动率和收益率 |
| 42%波动率 vs 大盘18% | 显示 "2.33x 远高于" |
| rebalance_suggestions 有 target_ratio | 非空具体数字 |

---

## 五、风险与约束

- **NIM 40 calls/min 限制**: 不受影响（不改调用次数）
- **模型输出不稳定**: 决策矩阵注入后 LLM 可能不完全遵守→需要 `_debate_synthesis` 做后处理校验
- **ActionResult 向后兼容**: 旧报告 DB 里的 action 是 Dict，新代码要兼容读取
- **历史对比需要两次分析**: 首次分析无上一期→`HistoricalComparison` 为空，正常
- **大盘基准净值**: 需要在 `advisor_service` 中抓取 510300 数据→可能需要 backfill

---

## 六、与已有文档的关系

| 文档 | 关系 |
|------|------|
| `RFC-004-quantitative-analysis-engine.md` | 基础架构，本 RFC 在此基础上增强 |
| `RFC-005-multi-model-debate.md` | 多模型分派，本 RFC 增强 debate 输出质量 |
| `optimization-v5.md` | 性能优化，独立于本 RFC |
| `bugfix-v5.md` | 已修 bug，本 RFC 不涉及已修项 |
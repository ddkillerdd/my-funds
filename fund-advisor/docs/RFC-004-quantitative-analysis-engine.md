# RFC-004: FundAdvisor 量化分析引擎 v3 — 极致完善版

## 调研摘要

调研了 20+ 个 GitHub 项目和学术论文，涵盖 AI 金融交易、多智能体架构、组合分析三大方向。

### 核心借鉴

| 项目 | 核心思路 | 我们怎么用 |
|------|---------|-----------|
| **TradingAgents** (95K⭐) | 7 角色多智能体: 基本面/技术面/情绪/新闻分析师 + 研究员 + 交易员 + 风控 → 辩论 → 基金经理决策 | 基金分析不需要交易，但"多分析师独立出结论→辩论→汇总"的架构直接复用 |
| **ai-hedge-fund** (50K⭐) | 18 个智能体各代表一位投资大师: 巴菲特/格雷厄姆/芒格/木头姐/伯里 → 各自分析 → PM 加权汇总 | 思路: 不做一个中立分析，而是多角度（价值派/成长派/技术派/风控派）各自给诊断 |
| **FinRobot** (AI4Finance) | 3 层 CoT: Data-CoT(数据汇总)→Concept-CoT(概念分析)→Thesis-CoT(投资论点生成) → 券商级研报 | 分层思路: 量化数据→信号解读→投资建议，每层递进且可追溯 |
| **pyfolio** (Quantopian) | 专业级 tear sheet: Sharpe/Sortino/Calmar/回撤分析/因子暴露/滚动指标 | 我们自己做量化计算，输出 LLM 可读的结构化指标卡 |
| **empyrical** (Quantopian) | 纯 Python 风险指标库: max_drawdown/annual_vol/sharpe/alpha/beta/omega/tail_ratio | 参考公式，自己轻量实现（避免重依赖） |
| **NoFx** (11K⭐) | 安全模式: 连续 3 次错误→自动停止交易→观察模式 | 对基金分析不直接适用，但"置信度衰减"机制可借鉴：当指标矛盾增多时标记分析可信度降低 |

### 关键洞察

1. **"辩论优于共识"**: ai-hedge-fund 的 18 个 agent 同时分析同一资产，让多方和空方 agent 辩论，结论比单体 LLM 好 24%（TradingAgents 论文数据）
2. **"先算后说"**: FinRobot 的 Data-CoT→Concept-CoT→Thesis-CoT 三级链，确保每个结论都有数据锚点
3. **"风格多样化"**: 单一分析视角（如纯量化或纯基本面）总有盲区，需多风格交叉验证
4. **"置信度标记"**: 当不同视角结论矛盾时，应标记为低置信度而非强行选一

---

## 最终架构: 4 视角 + 辩论 + 4 层计算

```
╔═══════════════════════════════════════════════════════════╗
║                  Layer 0: 数据引擎                          ║
║  AKShare / 天天基金 → fund_nav_history → pandas DataFrame  ║
╚═══════════════════════════════════════════════════════════╝
                          │
╔═══════════════════════════════════════════════════════════╗
║            Layer 1: 量化指标计算 (quant_engine.py)         ║
║  纯 Python 实现，零 ML 依赖，<1s 完成所有指标                ║
║                                                           ║
║  ┌─────────────────────────────────────────────────┐     ║
║  │          每只基金独立计算 (>30 项指标)               │     ║
║  ├───────────────┬───────────────┬─────────────────┤     ║
║  │ 趋势与动量     │ 风险与回撤     │ 收益与效率        │     ║
║  │ MA5/10/20/60  │ 年化波动率     │ 年化收益率        │     ║
║  │ 均线偏离度     │ 下行波动率     │ 累计收益率        │     ║
║  │ MACD(DIF/DEA) │ 最大回撤(%)    │ 月/季/半年/年收益  │     ║
║  │ 趋势强度(0-100)│ 回撤恢复天数    │ 月胜率           │     ║
║  │ RSI(14)       │ 最长回撤期      │ 盈亏比           │     ║
║  │ 近N天胜率     │ VaR(95%)       │ 超额收益(vs基准)  │     ║
║  │ 连涨/连跌天数  │ CVaR(95%)      │ Sharpe Ratio     │     ║
║  │ 价格位置(%)   │ Ulcer Index    │ Sortino Ratio    │     ║
║  │               │               │ Calmar Ratio     │     ║
║  │               │               │ 信息比率         │     ║
║  └───────────────┴───────────────┴─────────────────┘     ║
║                                                           ║
║  ┌─────────────────────────────────────────────────┐     ║
║  │             组合层面计算 (portfolio)                │     ║
║  │ 相关性矩阵 | HHI集中度 | β系数 | 行业分布 |         │     ║
║  │ 有效前沿(蒙特卡洛5000次) | 当前组合在有效前沿上位置   │     ║
║  │ 风险平价权重 vs 当前权重 vs 最优权重                  │     ║
║  └─────────────────────────────────────────────────┘     ║
╚═══════════════════════════════════════════════════════════╝
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
╔═══════════════════════════════════════════════════════════╗
║              Layer 2: 4 视角独立分析 (LLM)                ║
║                                                           ║
║  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    ║
║  │ 趋势面    │ │ 风险面    │ │ 价值面    │ │ 技术面    │    ║
║  │ Agent     │ │ Agent     │ │ Agent     │ │ Agent     │    ║
║  │           │ │           │ │           │ │           │    ║
║  │ MA偏离    │ │ 波动率    │ │ Sharpe    │ │ RSI/MACD  │    ║
║  │ 趋势强度  │ │ 最大回撤  │ │ 年化收益  │ │ 连涨连跌  │    ║
║  │ MACD金死叉│ │ VaR       │ │ 盈亏情况  │ │ 胜率      │    ║
║  │ 价格位置  │ │ 回撤特征  │ │ 基准对比  │ │ 价格形态  │    ║
║  │           │ │           │ │ 成本分析  │ │           │    ║
║  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └─────┬─────┘    ║
║        │              │              │              │       ║
║        ▼              ▼              ▼              ▼       ║
║   "趋势正在减弱"  "回撤可控"    "性价比一般"  "存在超卖"    ║
║   confidence:0.7  conf:0.8     conf:0.6     conf:0.65     ║
║                                                           ║
║  输出: 每视角 3-5 条诊断 + 置信度(0-1) + 引用指标+数值       ║
╚═══════════════════════════════════════════════════════════╝
                          │
╔═══════════════════════════════════════════════════════════╗
║          Layer 3: 辩论与综合 (LLM)                         ║
║                                                           ║
║  ┌─────────────────────────────────────────────────┐     ║
║  │          Debate Agent (综合裁判)                    │     ║
║  │                                                   │     ║
║  │ 输入: 4 视角各自诊断 + 完整量化数据                   │     ║
║  │                                                   │     ║
║  │ 任务:                                              │     ║
║  │  1. 识别 4 视角之间的矛盾                            │     ║
║  │     "趋势面说走弱,但技术面说超卖→存在争议"             │     ║
║  │  2. 判断矛盾严重程度                                 │     ║
║  │     无矛盾=置信度高 | 部分矛盾=中 | 严重矛盾=低        │     ║
║  │  3. 给出最终诊断                                     │     ║
║  │     健康度(0-100) + 3大风险 + 3大优势 + 操作建议      │     ║
║  │  4. 标注不确定项                                     │     ║
║  │     "净值历史<60天,趋势分析置信度有限"                │     ║
║  └─────────────────────────────────────────────────┘     ║
║                                                           ║
║  ┌─────────────────────────────────────────────────┐     ║
║  │       Portfolio Synthesizer (组合层面)              │     ║
║  │                                                   │     ║
║  │ 输入: 每只基金的 Debate 结果 + 组合相关性 + 有效前沿   │     ║
║  │                                                   │     ║
║  │ 输出:                                              │     ║
║  │  • 组合整体健康度                                   │     ║
║  │  • 集中度风险评估                                   │     ║
║  │  • 相关性分析 (哪两只同涨同跌,分散不足)              │     ║
║  │  • 调仓建议 (增持/减持/维持,带理由+参考数据)         │     ║
║  │  • 风险平价 vs 当前配置对比                          │     ║
║  │  • 有效前沿分析 (当前组合在哪个位置,优化方向)         │     ║
║  └─────────────────────────────────────────────────┘     ║
╚═══════════════════════════════════════════════════════════╝
                          │
╔═══════════════════════════════════════════════════════════╗
║          Layer 4: 报告合成 (Python, 无 LLM)              ║
║                                                           ║
║  整合 Layer 1(量化) + Layer 2(4视角) + Layer 3(辩论+组合)  ║
║  → 标准 JSON 报告                                        ║
║                                                           ║
║  报告结构:                                                ║
║  {                                                       ║
║    "ground_truth": {            // Layer 1 客观数据        ║
║      "portfolio": {...},                                  ║
║      "per_fund": [{num_indicators: 30+}, ...],           ║
║      "correlation_matrix": [[...], ...],                 ║
║      "efficient_frontier": {...}                         ║
║    },                                                     ║
║    "per_fund_diagnosis": [{     // Layer 2+3 每只基金       ║
║      "trend_view": {...},       // 趋势面诊断              ║
║      "risk_view": {...},        // 风险面诊断              ║
║      "value_view": {...},       // 价值面诊断              ║
║      "technical_view": {...},   // 技术面诊断              ║
║      "debate_summary": {        // 辩论结论                ║
║        "contradictions": [...],                            ║
║        "consensus_level": 0.72,                            ║
║        "health_score": 75,                                 ║
║        "risks": [...],                                     ║
║        "strengths": [...],                                 ║
║        "action": {"type":"hold/increase/decrease", ...}    ║
║      }                                                     ║
║    }],                                                     ║
║    "portfolio_diagnosis": {     // Layer 3 组合诊断        ║
║      "overall_health": 72,                                 ║
║      "concentration": "高度集中(白酒+H3C=75%)",            ║
║      "correlation_issues": [...],                          ║
║      "efficient_frontier_position": "below_frontier",      ║
║      "rebalance_suggestions": [...],                       ║
║      "risk_parity_comparison": {...}                       ║
║    },                                                      ║
║    "confidence": {              // 全局置信度               ║
║      "overall": 0.68,                                      ║
║      "data_quality": 0.9,        // 数据完整性             ║
║      "analysis_quality": 0.62,   // 分析质量(模型能力)      ║
║      "warnings": ["净值历史仅20天","无基准对比"]           ║
║    },                                                      ║
║    "model_chain": {...},                                   ║
║    "analysis_duration_seconds": 180                        ║
║  }                                                         ║
╚═══════════════════════════════════════════════════════════╝
```

---

## 量化指标详细定义

### 一、趋势与动量指标 (TrendView Agent 使用)

```python
# 趋势
ma5_price   → 5日简单移动均线
ma20_price  → 20日均线 (布林中轨)
ma60_price  → 60日均线 (牛熊分界线)
ma_deviation_pct → (当前净值-20日均线)/20日均线 × 100%
trend_strength → (当前净值-60日最低)/(60日最高-60日最低) × 100  # 0-100

# MACD
macd_dif    → 12日EMA - 26日EMA
macd_dea    → DIF的9日EMA
macd_hist   → 2 × (DIF - DEA)  # 柱状图
macd_signal → "金叉"/"死叉"/"多头"/"空头"/"拐点"

# 动量
rsi_14      → RSI(14), 超买>70, 超卖<30
win_rate_20 → 近20天上涨天数/20 × 100%  # 赚钱概率
win_rate_60 → 近60天上涨天数/60 × 100%
consecutive_up   → 连续上涨天数
consecutive_down → 连续下跌天数
price_position   → 当前净值在60日区间中的位置(%)  # 0%=最低点,100%=最高点
```

### 二、风险与回撤指标 (RiskView Agent 使用)

```python
# 波动率
annual_volatility  → std(daily_returns) × sqrt(252) × 100%  # 年化波动率
downside_volatility → std(neg_returns) × sqrt(252) × 100%    # 下行波动

# 最大回撤
max_drawdown_pct     → max(1 - nav/peak) × 100%
max_drawdown_start   → 回撤开始日期
max_drawdown_end     → 回撤最低点日期
max_drawdown_recovery → 回撤恢复天数 (回到前高所需)
max_drawdown_duration → 回撤持续时间 (峰值到谷底)
current_drawdown_pct → 当前距历史高点的回撤%

# VaR (历史模拟法)
var_95_daily → 收益率序列的5%分位数 × -1  # 95%置信度每日最大亏损
cvar_95_daily→ var_95以下所有收益率的均值 × -1  # 条件VaR(尾部风险)

# Ulcer Index (彼得·马丁)
ulcer_index → sqrt(mean(平方回撤))  # 综合考虑回撤深度和持续时间

# 波动率状态
volatility_regime → "低波"(<15%)/"中波"(15-25%)/"高波"(25-35%)/"极高波"(>35%)
```

### 三、收益与效率指标 (ValueView Agent 使用)

```python
# 收益
annual_return       → (终值/初值)^(252/n) - 1  # 年化复合收益率
cumulative_return   → (终值-初值)/初值 × 100%
return_1m_3m_6m_1y  → 最近1/3/6/12月收益率
monthly_win_rate    → 月收益>0的月数/总月数
profit_loss_ratio   → Σ(正收益)/|Σ(负收益)|  # 盈亏比
best_day_return     → 最佳单日收益
worst_day_return    → 最差单日收益

# 综合效率
sharpe_ratio        → (年化收益 - 无风险利率) / 年化波动率
sortino_ratio       → (年化收益 - 无风险利率) / 下行波动率
calmar_ratio        → 年化收益 / |最大回撤|
information_ratio   → 超额收益 / 跟踪误差 (vs 沪深300)
omega_ratio         → Σmax(0, 超额收益) / Σ|min(0, 超额收益)|

# 基准对比
excess_return_vs_benchmark → 基金年化收益 - 沪深300年化收益
beta_to_benchmark    → 相对基准的β系数
alpha_to_benchmark   → Jensen's α
tracking_error       → 跟踪误差
capture_ratio_up     → 基准上涨时基金的涨幅/基准的涨幅
capture_ratio_down   → 基准下跌时基金的跌幅/基准的跌幅
```

### 四、技术面信号 (TechnicalView Agent 使用)

```python
# 形态信号
rsi_signal     → "超买"/"超卖"/"中性" (基于RSI值)
macd_signal    → "金叉"/"死叉"/"多头"/"空头" (基于MACD)
ma_signal      → "多头排列"/"空头排列"/"金叉"/"死叉" (MA5/20/60关系)
bollinger_position → 净值在布林带的位置 (上/中/下轨)

# Bollinger Bands
bollinger_upper → MA20 + 2σ
bollinger_mid   → MA20
bollinger_lower → MA20 - 2σ
bollinger_width → (上轨-下轨)/中轨 × 100%  # 带宽, 收窄=变盘前兆

# 成交量(如果有)
vol_trend     → 近5日均量 vs 近20日均量
vol_price_divergence → 量价背离标志

# 综合信号
technical_rating → 0-100 综合技术评分
rating_breakdown  → {趋势: 70, 动量: 55, 形态: 60, 成交量: 45}
```

### 五、组合层面指标

```python
# 相关性
correlation_matrix → N×N 矩阵 Pearson相关系数
avg_pairwise_corr  → 平均两两相关性
corr_warning_pairs  → [("161725","012345"), ...]  # 相关性>0.8的基金对

# 集中度
hhi_index          → Σ(占比²)  # Herfindahl Index, >0.25=高度集中
concentration_top1 → 最大单只占比
concentration_top3 → 前三大占比

# 有效前沿 (蒙特卡洛模拟)
efficient_frontier_points  → 5000次随机权重模拟的(风险,收益)散点
optimal_sharpe_weights     → 最大夏普比率对应的权重
min_volatility_weights     → 最小波动率对应的权重
current_portfolio_position → 当前组合在有效前沿上的位置:
  {
    "risk": 18.5,           # 当前组合年化波动
    "return": 12.3,         # 当前组合年化收益
    "distance_to_frontier": 2.1,  # 距有效前沿的距离(%)
    "position_quality": "suboptimal",  # optimal/near_optimal/suboptimal/poor
    "to_optimal": {          # 达到最优夏普权需要的调整
      "161725": {"current": 0.25, "target": 0.18, "change": -0.07},
      ...
    }
  }

# 相对于基准
style_analysis_weights → 风格分析 (大盘/小盘, 价值/成长)
```

---

## LLM 调用设计

### 模型分配

| Agent | 模型 | 输入 | 输出 | 调用次数 |
|-------|------|------|------|---------|
| TrendView | nemotron-nano-9b | 趋势+动量指标卡 | 诊断+置信度 | N次(每只基金) |
| RiskView | nemotron-nano-9b | 风险+回撤指标卡 | 诊断+置信度 | N次 |
| ValueView | nemotron-nano-9b | 收益+效率指标卡 | 诊断+置信度 | N次 |
| TechnicalView | nemotron-nano-9b | 技术面信号卡片 | 诊断+置信度 | N次 |
| Debate (per fund) | nemotron-nano-9b | 4视角诊断+全部数据 | 综合诊断+矛盾分析 | N次 |
| Portfolio Synthesizer | nemotron-nano-9b | 辩论结论+组合指标 | 组合诊断+调仓建议 | 1次 |
| Cross-Validation | nemotron-nano-9b | 整个报告草稿 | 验证通过/问题列表 | 1次 |

**LLM 调用总数**: 5N + 2 (N=基金数, e.g. 4只→22次, 10只→52次)

**注意**: 可优化为每只基金的4视角分析合并在一次 LLM 调用中（prompt 分区），减少到 N+2 次。但考虑 nemotron-nano 的质量，分开调更精准。先分开，效果好再优化。

### 预期耗时

| 场景 | 基金数 | 调用次数 | 单次延迟 | 总耗时 |
|------|--------|---------|---------|--------|
| 小组合 | 4 | 22 | 1-2s | 44-88s |
| 中组合 | 10 | 52 | 1-2s | 104-208s |
| 大组合 | 20 | 102 | 1-2s | 204-408s |

### 温度设置

- 4 视角 Agent: temperature=0.3 (需要一定创造力，但数据引述要准)
- Debate Agent: temperature=0.1 (需保守判断)
- Portfolio Synthesizer: temperature=0.1
- Cross-Validation: temperature=0

---

## Prompt 设计原则

1. **数据引用强制**: 每个结论必须引用量化指标的具体数值
2. **置信度强制**: 每条诊断带 0-1 置信度
3. **不确定性标注**: 数据不足时明确标注
4. **JSON only 输出**: 严格 JSON 格式,解析失败有降级
5. **避免幻觉**: 明确告知 LLM "只基于提供的数据,不要编造未知信息"

示例 TrendView prompt 结构：

```
你是基金趋势面分析师。基于以下纯计算得出的量化指标,
分析基金[代码][名称]的趋势和动量状况。

【客观数据 - 由 Python 计算,100%准确,请务必引用】
- MA5: 1.245 | MA20: 1.238 | MA60: 1.201
- 当前净值 1.251, 站上所有均线 (MA偏离+1.05%)
- MACD: DIF:0.008, DEA:0.005, 柱:0.003 → 金叉多头中
- 趋势强度: 82/100 (强势)
- RSI(14): 58.3 (中性偏强, 未超买)
- 20日胜率: 55% | 60日胜率: 57%
- 连涨: 3天
- 价格位置: 78% (60日区间)

【要求】
1. 输出标准 JSON
2. 每条诊断引用具体数值
3. 标注置信度(0-1)
4. 数据不足时注明

{
  "fund_code": "161725",
  "diagnosis": [
    {"claim": "...", "confidence": 0.85, "evidence": "MA5=1.245 > MA20=1.238, 净值=1.251站上所有均线"},
    ...
  ],
  "overall_trend_score": 75,   // 0-100, 趋势健康度
  "trend_direction": "up",     // up/sideways/down
  "trend_strength_label": "强势",
  "key_risk": "...",
  "key_opportunity": "...",
  "uncertainties": []
}
```

---

## 与现有 v2 代码的关系

| 文件 | v2 状态 | v3 变更 |
|------|---------|---------|
| `facts_computer.py` | 简单盈亏/占比/净值列表 | **重写为 quant_engine.py**：所有量化指标 |
| `advisor_service.py` | 4-step 单视角分析 | **重写**: 4 视角 + Debate + 组合综合 |
| `advisor.py` (API) | 不变 | 响应字段新增 quant_indicators、views、debates、confidence |
| AdvisorView.vue | 已有历史/健康度/验证 | 新增：4 视角面板、置信度徽章、量化指标展开 |

---

## 实施计划

### Phase 1: quant_engine.py (核心, 最优先)
- 所有量化指标的纯 Python 实现
- 输入: fund_nav_history + holdings
- 输出: 标准化指标 dict (每只基金30+项 + 组合10+项)
- 无需 LLM，纯 pandas/numpy

### Phase 2: 4 视角 Prompt + LLM 调用
- 4 个 Agent 的 system prompt 模板
- 新增 `_analyze_trend_view()` 等 4 个方法
- 输入: 量化指标卡, 输出: 诊断 JSON

### Phase 3: Debate + Portfolio Synthesizer
- 新增 `_debate_per_fund()`: 综合 4 视角 → 最终诊断
- 新增 `_synthesize_portfolio()`: 组合层面建议
- Cross-Validation 保留现有实现

### Phase 4: 前端改造
- 新增量化指标面板 (可折叠)
- 新增 4 视角诊断面板 (标签页切换)
- 新增置信度可视化
- 新增有效前沿图表

### Phase 5: 基金推荐引擎
- 独立于现有分析系统
- 基于基金筛选指标 (Sharpe/回撤/波动率/规模/)
- 输出推荐排名 + 理由

---

## 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| nemotron-nano 分析质量不足 | 中 | 诊断不专业 | 可用 mistral-large-3 替代 (目前配额低) |
| 22 次 LLM 调用耗时过长 | 高 | 4只基金需88s | 合并 4 视角为单次调用 (N+2次) |
| 有效前沿计算对 2 只基金无意义 | 低 | 组合分析空洞 | 基金数<3时跳过有效前沿 |
| 净值历史不足 (e.g. <30天) | 高 | 多个指标无法计算 | 标注缺失, 阈值下调, 仅用可用指标 |

---

## 关键性能指标 (KPI)

1. **诊断引用密度**: 每条 LLM 诊断至少引用 1 个量化指标数值
2. **矛盾检出率**: 辩论 Agent 检测到至少 1 条视角间矛盾
3. **置信度分布**: overall_confidence 不低于 0.5 (数据不足时≤0.5)
4. **操作建议具体度**: 调仓建议含具体百分比或金额
5. **分析可追溯性**: 每条结论可以追溯到具体的量化指标或 LLM Agent

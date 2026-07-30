# FundAnalyzer — 开发文档 v2（多轮调研验证版）

> 调研了 AI4Finance/FinRobot (学术论文+桌面版)、virattt/ai-hedge-fund (50K⭐ ROADMAP+VISION)、TauricResearch/TradingAgents (95K⭐ 论文+源码)、DX Research Group (提示工程实验)、Quantopian pyfolio/empyrical 等 20+ 项目。以下是经过多轮交叉验证后确定的设计。

---

## 一、核心方法论（从顶级项目中学到的）

### 1. 提示工程决定分析质量的 70%

DX Research Group 的实验数据：同一句"2.3%交易费用"放在 prompt 第一段 vs 第八段，LLM 的引用率从 3% 跳到 74%。**读取顺序改变观察到的行为。**

→ **结论**：量化指标必须放在 prompt 最前面、最显著位置，要求 LLM"必读必引"。

### 2. 多角色辩论比单体分析好 24%

TradingAgents 论文的核心发现：多分析师独立出结论 → 多方/空方辩论 → 基金经理汇总，累计收益 26.6% vs 基准 (B&H -5.2%)。关键不是角色多，是**角色之间的矛盾被检测并裁决**。

→ **结论**：不是简单让多个 LLM 分别分析然后投票，而是要求 Debate Agent 显式列出矛盾、逐条裁决。

### 3. 量化层必须先于 LLM 层

FinRobot 3 层 CoT（Data→Concept→Thesis）的精髓：第一层纯数据处理（不用 LLM），第二层概念分析（LLM 在数据基础上推理），第三层报告生成（LLM 写报告）。**LLM 只做推理和写作，不做计算。**

→ **结论**：所有量化指标 Python 算好，LLM prompt 里只给"事实卡"，不给原始数据。LLM 被要求"引用这些数据"而非"分析这些数据"。**这是防止幻觉的最有效手段。**

### 4. 历史记忆提高连续性

TradingAgents 的 Decision Log：每次分析结果写入 `trading_memory.md`，下次分析时注入最近同标的决策 + 实际收益，生成一句话反思。Portfolio Manager 做决策时能看到"上次我们判断对了/错了"。

→ **结论**：分析系统应记住上次对该基金的分析，比对实际走势。分析准确度有迹可循。

### 5. 风格多样性是 Alpha 来源

ai-hedge-fund 18 个 agent 各代表一位投资大师（巴菲特、木头姐、伯里……），各自从不同哲学角度看同一只股票。Portfolio Manager 不是选一个相信，而是**根据近期准确率加权汇总**。

→ **结论**：4 个视角（趋势/风险/价值/技术）应各自独立分析，不做中庸妥协。出现分歧时不是"取平均"，而是"指出矛盾、降低置信度、让用户判断"。

### 6. 置信度标记比结论本身更重要

NoFx 的安全模式：连续 3 次预测错误 → 自动停用。这个机制的前提是系统知道自己什么时候不确定。

→ **结论**：每条诊断、每个视角、综合结论都有 confidence(0-1)。overall_confidence < 0.5 时明确提示"当前分析可信度有限，不建议作为决策依据"。

---

## 二、最终架构

```
fund-analyzer/                    # 独立项目，零耦合
│
├── README.md                     # 概述 + 快速开始
├── DESIGN.md                     # 本文（设计文档）
├── REQUIREMENTS.md               # 依赖 + 环境要求
│
├── engine/
│   ├── __init__.py
│   ├── models.py                 # 所有 dataclass 定义
│   │   ├── FundHolding           # 输入：持仓
│   │   ├── NavPoint              # 输入：净值点
│   │   ├── QuantIndicators       # 量化指标容器 (30+字段)
│   │   ├── ViewDiagnosis         # 单个视角的诊断输出
│   │   ├── FundDiagnosis         # 单基金完整诊断
│   │   ├── PortfolioInput        # 输入：完整投资组合
│   │   └── AnalysisReport        # 输出：完整报告
│   │
│   ├── quant.py                  # 量化指标计算
│   │   ├── compute_trend()       # MA/MACD/趋势强度
│   │   ├── compute_momentum()    # RSI/胜率/布林带
│   │   ├── compute_risk()        # 波动率/回撤/VaR
│   │   ├── compute_returns()     # 收益/年化/月胜率
│   │   ├── compute_efficiency()  # Sharpe/Sortino/Calmar/IR/Omega
│   │   ├── compute_benchmark()   # α/β/跟踪误差/Capture
│   │   └── compute_all()         # 统一入口，返回 QuantIndicators
│   │
│   ├── portfolio_quant.py        # 组合层面量化
│   │   ├── correlation_matrix()  # 相关性矩阵
│   │   ├── concentration()       # HHI/集中度
│   │   ├── efficient_frontier()  # 蒙特卡洛模拟
│   │   └── risk_parity()         # 风险平价权重
│   │
│   ├── prompts.py                # LLM Prompt 模板
│   │   ├── TREND_VIEW_PROMPT     # 趋势面分析 prompt
│   │   ├── RISK_VIEW_PROMPT      # 风险面分析 prompt
│   │   ├── VALUE_VIEW_PROMPT     # 价值面分析 prompt
│   │   ├── TECHNICAL_VIEW_PROMPT # 技术面分析 prompt
│   │   ├── DEBATE_PROMPT         # 辩论综合 prompt
│   │   ├── PORTFOLIO_PROMPT      # 组合诊断 prompt
│   │   ├── CROSS_VALID_PROMPT    # 交叉验证 prompt
│   │   └── build_fact_card()     # 把 QuantIndicators 转成 LLM 事实卡
│   │
│   ├── llm_client.py             # LLM 调用封装
│   │   ├── LLMClient(config)     # 构造 client
│   │   ├── call(prompt, model, temp, max_tokens) → str
│   │   ├── parse_json(raw) → dict | None
│   │   └── fallback_decision()   # LLM 失败时的降级方案
│   │
│   └── analyzer.py               # 主分析流程
│       ├── Analyzer(config)      # 构造函数
│       ├── analyze(portfolio) → AnalysisReport
│       └── _step_*()             # 各步骤实现
│
├── tests/
│   ├── fixtures/
│   │   ├── mock_portfolio.json   # 模拟持仓（含净值历史）
│   │   └── mock_nav_data.json    # 模拟净值数据
│   ├── test_quant.py             # 量化指标单元测试
│   ├── test_portfolio_quant.py   # 组合量化单元测试
│   ├── test_prompts.py           # Prompt 模板测试（不调 LLM）
│   ├── test_analyzer.py          # 集成测试（调 LLM）
│   └── conftest.py               # pytest fixtures
│
├── docs/
│   └── bug-report-template.md    # Bug 报告模板
│
└── requirements.txt              # pandas numpy httpx (全部已有)
```

---

## 三、Prompt 设计规范（关键）

### 3.1 量化指标放最前面（DX Research 法则）

```python
TREND_VIEW_PROMPT = """
你是基金趋势面分析师。分析以下基金的**趋势与动量状况**。

## ⚠️ 核心规则
1. 只基于下方「量化事实卡」中的数据做判断，不要编造任何你「觉得应该有」的信息
2. 每条诊断必须引用至少1个量化指标的具体数值（格式: (指标名=数值)）
3. 数据不足时，在 uncertainties 里明确标注，不要在诊断里猜
4. 输出标准 JSON，不要 Markdown 包裹

## 量化事实卡（Python 计算，100% 准确）
{fact_card}    ← 这是 prompt 中最前面的内容块，确保 LLM 先读

## 输出格式
{output_schema}

## 内容要求
- diagnosis: 3-5条诊断，每条含 claim/confidence/evidence/sentiment
- overall_score: 0-100 趋势健康度
- 方向判断: up/sideways/down
"""
```

### 3.2 每条诊断的证据锚定

```json
{
  "claim": "MA多头排列确认上升趋势",
  "confidence": 0.85,
  "evidence": "(净值1.251 > MA5=1.245 > MA20=1.238 > MA60=1.201)",
  "sentiment": "positive"
}
```

evidence 字段不是可选、不是建议、是**强制**。没有 evidence 的诊断即为不合格输出。

### 3.3 温度差异化

| Agent | 温度 | 原因 |
|-------|------|------|
| TrendView | 0.3 | 需要一定灵活性，但数据引用必须准 |
| RiskView | 0.3 | 同上 |
| ValueView | 0.2 | 收益数据更需要精确解读 |
| TechnicalView | 0.3 | RSI/MACD 形态判断需要灵活性 |
| Debate | 0.1 | 裁判必须保守，不可随意 |
| Portfolio | 0.1 | 调仓建议影响大，必须谨慎 |
| CrossValid | 0 | 验证不允许出错 |

### 3.4 JSON Schema 强制

每个 prompt 的 output_schema 写死 JSON 结构。用 `parse_json()` 提取后，对缺失字段立即降级，不猜测。

### 3.5 失败降级链（nemotron 优先）

```
尝试1: nemotron-nano-9b (temperature=按角色, max_tokens=2048, timeout=60s)
  ↓ 失败
尝试2: deepseek-v4-flash (opencode, temperature=0, max_tokens=4096, timeout=90s)
  ↓ 失败
降级: 纯计算降级（基于量化指标直接评分，不调用 LLM）
```

---

## 四、输出报告完整 JSON Schema

见 DESIGN.md 中的 schema，此处补充新增的字段：

```json
{
  // ============ 新增: 历史滚动对比 ============
  "historical_comparison": {
    "previous_report_id": null,           // 上次分析ID (首次为null)
    "previous_generated_at": null,
    "changes": [                          // 相对上次的关键变化
      {
        "fund_code": "161725",
        "dimension": "trend_score",
        "previous": 65,
        "current": 75,
        "delta": "+10",
        "interpretation": "趋势从中性转为强势 (MA5上穿MA20)"
      }
    ],
    "prediction_accuracy": null           // 上次预测准确性 (首次为null)
  },

  // ============ 新增: 降级标记 ============
  "degradation": {
    "any_degraded": false,                // 是否有任何步骤走了降级
    "degraded_steps": [],                 // ["trend_view_161725"] 等
    "impact": "none"                      // none/minor/moderate/severe
  },

  // ============ 新增: 分析完整性 ============
  "completeness": {
    "total_indicators_computed": 28,      // 实际计算出的指标总数
    "total_indicators_expected": 32,      // 理论最大指标数
    "completeness_pct": 87.5,
    "missing_indicators": [              // 因数据不足未计算的指标
      {"name": "return_1y_pct", "reason": "净值历史仅120天，不足252天"},
      {"name": "omega_ratio", "reason": "需要日级别基准数据"}
    ],
    "data_quality_label": "adequate"      // good/adequate/sparse/insufficient
  }
}
```

---

## 五、实施阶段

### Phase 1: models.py + quant.py（纯 Python，无 LLM）
- 定义所有 dataclass（输入/输出结构）
- 实现全部 32 项量化指标计算
- 单元测试验证指标正确性
- 时间: 估计 4-6 小时

### Phase 2: prompts.py + llm_client.py（LLM 基础设施）
- 7 个 Agent 的 prompt 模板
- LLM 调用封装（含 fallback 链）
- build_fact_card() 将量化指标转为 LLM 可读文本
- 时间: 估计 2-3 小时

### Phase 3: analyzer.py（主流程编排）
- 5 步流水线编排
- 各步骤结果合并
- 降级/缺失标注
- 集成测试
- 时间: 估计 3-4 小时

### Phase 4: 集成到 FundAdvisor
- FundAdvisor 调用 fund-analyzer
- API 兼容旧报告
- 前端新增量化面板
- 时间: 估计 2-3 小时

---

## 六、测试策略

### 6.1 单元测试（不调 LLM）

```python
# test_quant.py
def test_compute_trend_with_full_data():
    """120天净值历史 → 完整趋势指标"""
    indicators = compute_trend(mock_nav_120d)
    assert indicators.ma5 is not None
    assert indicators.trend_strength is not None
    assert 0 <= indicators.trend_strength <= 100

def test_compute_trend_with_sparse_data():
    """10天净值历史 → 部分指标缺失但不出错"""
    indicators = compute_trend(mock_nav_10d)
    assert indicators.ma5 is not None       # 10天可以算MA5
    assert indicators.ma60 is None          # 不能算MA60
    assert len(indicators.notes) > 0        # 有标注

def test_sharpe_ratio_calculation():
    """验证 Sharpe 公式正确性"""
    ...

def test_max_drawdown_known_scenario():
    """验证最大回撤计算"""
    ...
```

### 6.2 集成测试（调 LLM）

```python
# test_analyzer.py
def test_full_analysis_with_mock_data():
    """完整的分析流程，输出符合 schema"""
    analyzer = Analyzer(config)
    report = analyzer.analyze(mock_portfolio_4funds)
    assert report.ground_truth is not None
    assert len(report.per_fund_diagnosis) == 4
    for fd in report.per_fund_diagnosis:
        assert 0 <= fd.debate_summary.health_score <= 100
        assert fd.debate_summary.consensus_level > 0
    assert report.portfolio_diagnosis.overall_health_score > 0

def test_analysis_with_insufficient_data():
    """数据不足时不崩溃，正确标注"""
    analyzer = Analyzer(config)
    report = analyzer.analyze(mock_portfolio_3day_history)
    assert report.confidence.overall < 0.5       # 历史太短
    assert len(report.confidence.warnings) >= 2

def test_fallback_when_llm_fails():
    """LLM 全部超时时，降级正确"""
    analyzer = Analyzer(config_with_bad_endpoint)
    report = analyzer.analyze(mock_portfolio_4funds)
    assert report.degradation.any_degraded is True
    assert report.degradation.impact == "severe"
    # 降级后仍有基本结论
    assert len(report.per_fund_diagnosis) == 4
```

### 6.3 质量测试

```python
def test_every_diagnosis_has_evidence():
    """每条诊断都有 evidence 引用"""
    ...

def test_no_hallucination_numbers():
    """诊断中引用的数值都在量化指标中存在"""
    ...

def test_high_contradiction_lowers_confidence():
    """矛盾多的分析置信度应更低"""
    ...
```

---

## 七、质量保证清单

-[ ] 每条 LLM 诊断引用 ≥1 个量化指标数值（evidence 字段非空）
-[ ] 所有量化指标 Python 计算，零 LLM 参与
-[ ] 数据不足时明确标注而非猜测（uncertainties 字段）
-[ ] 视角间矛盾被显式列出并裁决
-[ ] overall_confidence < 0.5 时有显著警告
-[ ] 降级路径完整可用（nemotron → deepseek → 纯计算）
-[ ] 支持 2-20 只基金的分析
-[ ] 分析耗时预估值与实际偏差 <30%
-[ ] JSON Schema 严格，解析失败有降级
-[ ] 历史对比功能正常工作（首次/非首次）

"""
LLM Prompt Templates for FundAnalyzer

Each agent gets a custom prompt with:
1. Quant fact card at TOP (DX Research rule: first-read = most-cited)
2. Specific output JSON schema
3. Temperature-appropriate role description
4. Mandatory evidence citation requirement
"""

from __future__ import annotations
from typing import List, Optional

from .models import QuantIndicators, FundHolding


def build_fact_card(qi: QuantIndicators) -> str:
    """
    Build a structured fact card from quant indicators.
    This is placed at the TOP of every LLM prompt.
    Format: Chinese labels, numerical values, nulls explicitly marked "N/A".
    """

    def v(val, suffix="", precision=2):
        """Format value or mark as N/A"""
        if val is None:
            return "N/A"
        if isinstance(val, float):
            if precision == 0:
                return f"{int(val)}{suffix}"
            return f"{val:.{precision}f}{suffix}"
        if isinstance(val, int):
            return f"{val}{suffix}"
        return f"{val}{suffix}"

    parts = []

    # === Header ===
    parts.append(f"基金代码: {qi.fund_code}")
    parts.append(f"基金名称: {qi.fund_name}")
    parts.append(f"基金类型: {qi.fund_type}")
    parts.append(f"货币基金: {'是' if qi.is_money_fund else '否'}")
    parts.append(f"净值数据天数: {qi.nav_history_days}")
    parts.append(f"数据质量评级: {qi.data_quality}")
    parts.append("")

    # === Portfolio Position ===
    parts.append("【持仓信息】")
    parts.append(f"当前市值: {v(qi.current_mv)}元")
    parts.append(f"持有成本: {v(qi.cost)}元")
    parts.append(f"浮动盈亏: {v(qi.pnl_amount)}元 ({v(qi.pnl_pct)}%)")
    parts.append(f"占组合比例: {v(qi.mv_ratio)}%")
    parts.append("")

    # === Trend ===
    parts.append("【均线与趋势】")
    parts.append(f"当前净值: {v(qi.trend.current_nav)}")
    parts.append(f"MA5: {v(qi.trend.ma5)}  MA10: {v(qi.trend.ma10)}  MA20: {v(qi.trend.ma20)}  MA60: {v(qi.trend.ma60)}  MA120: {v(qi.trend.ma120)}")
    parts.append(f"净值偏离MA20: {v(qi.trend.ma_deviation_pct, '%')}")
    parts.append(f"均线排列状态: {qi.trend.ma_status}")
    parts.append(f"趋势方向: {qi.trend.trend_direction}")
    parts.append(f"趋势强度评分(0-100): {v(qi.trend.trend_strength, precision=0)}")
    parts.append(f"60日区间位置: {v(qi.trend.price_position_pct, '%', 1)}")
    # Only show macd here
    parts.append(f"连续定向天数: {qi.trend.consecutive_direction_days}")
    parts.append("")

    # === MACD ===
    parts.append("【MACD 指标(12,26,9)】")
    parts.append(f"DIF: {v(qi.macd.dif)}  DEA: {v(qi.macd.dea)}  MACD柱: {v(qi.macd.histogram)}")
    parts.append(f"MACD信号: {qi.macd.signal}")
    if qi.macd.divergence_type:
        parts.append(f"背离检测: {qi.macd.divergence_type}")
    parts.append("")

    # === Momentum ===
    parts.append("【动量指标】")
    parts.append(f"RSI(14): {v(qi.momentum.rsi_14, precision=1)} → {qi.momentum.rsi_signal}")
    parts.append(f"日胜率: 20日{v(qi.momentum.win_rate_20, '%', 1)}  60日{v(qi.momentum.win_rate_60, '%', 1)}")
    parts.append(f"连续上涨天数: {qi.momentum.consecutive_up_days}  连续下跌天数: {qi.momentum.consecutive_down_days}")
    parts.append(f"布林带: 上轨{v(qi.momentum.bollinger_upper)} / 中轨{v(qi.momentum.bollinger_mid)} / 下轨{v(qi.momentum.bollinger_lower)}")
    parts.append(f"布林带位置: {qi.momentum.bollinger_position}  带寛: {v(qi.momentum.bollinger_width_pct, '%')}")
    parts.append("")

    # === Risk ===
    parts.append("【风险指标】")
    parts.append(f"年化波动率: {v(qi.risk.annual_volatility_pct, '%')}  下行波动率: {v(qi.risk.downside_volatility_pct, '%')}")
    parts.append(f"波动率分区: {qi.risk.volatility_regime}")
    parts.append(f"最大回撤: {v(qi.risk.max_drawdown_pct, '%')} (从{qi.risk.max_drawdown_start or 'N/A'} 至 {qi.risk.max_drawdown_end or 'N/A'})")
    if qi.risk.max_drawdown_duration_days:
        parts.append(f"最大回撤持续: {qi.risk.max_drawdown_duration_days}天  恢复用时: {v(qi.risk.max_drawdown_recovery_days, '天', 0) if qi.risk.max_drawdown_recovery_days else 'N/A'}")
    parts.append(f"当前回撤: {v(qi.risk.current_drawdown_pct, '%')}")
    parts.append(f"VaR(95%每日): {v(qi.risk.var_95_daily_pct, '%')}  CVaR(95%每日): {v(qi.risk.cvar_95_daily_pct, '%')}")
    parts.append(f"Ulcer Index: {v(qi.risk.ulcer_index)}")
    parts.append("")

    # === Returns ===
    parts.append("【收益表现】")
    parts.append(f"近1月收益: {v(qi.returns.return_1m_pct, '%')}  近3月: {v(qi.returns.return_3m_pct, '%')}")
    parts.append(f"近6月收益: {v(qi.returns.return_6m_pct, '%')}  近1年: {v(qi.returns.return_1y_pct, '%')}")
    parts.append(f"年化收益: {v(qi.returns.annual_return_pct, '%')}  累计收益: {v(qi.returns.cumulative_return_pct, '%')}")
    parts.append(f"月胜率: {v(qi.returns.monthly_win_rate, '%', 1)}  日盈亏比: {v(qi.returns.profit_loss_ratio)}")
    parts.append(f"最佳单日: +{v(qi.returns.best_day_pct, '%')}  最差单日: {v(qi.returns.worst_day_pct, '%')}")
    parts.append("")

    # === Efficiency ===
    parts.append("【效率与风险调整收益】")
    parts.append(f"Sharpe Ratio: {v(qi.efficiency.sharpe_ratio)}  (好坏分界线: 1.0)")
    parts.append(f"Sortino Ratio: {v(qi.efficiency.sortino_ratio)}  (好坏分界线: 1.0)")
    parts.append(f"Calmar Ratio: {v(qi.efficiency.calmar_ratio)}  (收益与最大回撤之比)")
    parts.append(f"Omega Ratio: {v(qi.efficiency.omega_ratio)}  (好坏分界线: 1.0)")

    # Information ratio only if benchmark
    if qi.efficiency.information_ratio is not None:
        parts.append(f"Information Ratio: {v(qi.efficiency.information_ratio)}")

    parts.append("")

    # === Benchmark (if available) ===
    if qi.benchmark:
        parts.append("【基准对比】")
        parts.append(f"超额收益(vs基准): {v(qi.benchmark.excess_return_pct, '%')}")
        parts.append(f"Beta: {v(qi.benchmark.beta)}  Alpha: {v(qi.benchmark.alpha)}")
        parts.append(f"跟踪误差: {v(qi.benchmark.tracking_error, '%')}")
        parts.append(f"上行捕获率: {v(qi.benchmark.capture_up, '%')}  下行捕获率: {v(qi.benchmark.capture_down, '%')}")
        parts.append("")

    # === Data Quality Notes ===
    if qi.all_notes:
        parts.append("【数据质量备注】")
        for note in qi.all_notes:
            parts.append(f"⚠ {note}")
        parts.append("")

    return "\n".join(parts)


# ============================================================
#  PROMPT TEMPLATES
# ============================================================

def _base_rules() -> str:
    return """## ⚠️ 核心规则（必须遵守）
1. 你只能基于下方「量化事实卡」中的数据做判断。不要编造、猜测或假设任何不在事实卡中的信息。
2. 每条诊断（diagnosis[].claim）必须引用至少1个量化指标的具体数值，写在 evidence 字段中，格式: (指标名称=具体数值)。
3. 对于事实卡中标注为 "N/A" 的数据，视为不可用，在 uncertainties 中标注它，但不要在 diagnosis 中基于它做判断。
4. 数据质量评级为 "insufficient" 或 "sparse" 时，降低对应视角的 confidence。
5. 输出严格 JSON，不要用 Markdown 代码块包裹。只输出 JSON 对象。"""


TREND_VIEW_PROMPT = """你是基金趋势面分析师。你的任务是分析一只基金的**趋势与动量状况**。

角色: 你擅长识别多空趋势、均线排列、MACD金叉死叉、趋势强度评估。你对假突破和噪音有高度敏感性。

{base_rules}

## 量化事实卡（Python 计算，100% 准确）
{fact_card}

## 输出 JSON Schema（严格按此输出）
```json
{{
  "overall_trend_score": 75,
  "trend_direction": "up",
  "trend_strength_label": "强势",
  "diagnosis": [
    {{
      "claim": "短期均线系统形成多头排列，趋势确认上行",
      "confidence": 0.85,
      "evidence": "(净值=1.251 > MA5=1.245 > MA20=1.238, 全部在均线上方)",
      "sentiment": "positive"
    }}
  ],
  "key_risk": "MACD柱状缩小，上升动能减弱，警惕顶背离",
  "key_opportunity": "均线多头排列确认中期趋势",
  "confidence": 0.80,
  "uncertainties": ["N/A如有不确定性写在这里"]
}}
```

## 内容质量要求
- diagnosis: 3-5条独立的诊断
- claim: 20-50字的中文诊断陈述
- confidence: 0-1, 完全确定=1.0, 完全不确定=0
- evidence: 必须用 "()" 标注引用的量化指标，如 "(MA5=1.245, RSI=58.3)"
- sentiment: positive/negative/neutral
- overall_trend_score: 0-100 整数，70+为强趋势，40-60为中性
- trend_direction: up/sideways/down
- trend_strength_label: 强势/偏强/中性/偏弱/弱势
- key_risk / key_opportunity: 各1-2句话
- confidence: 0-1, 基于数据质量和信号一致性的总体信心
"""


RISK_VIEW_PROMPT = """你是基金风险面分析师。你的任务是评估一只基金的**风险暴露与下行保护能力**。

角色: 你极度厌恶风险，总是悲观地看待数据。你擅长发现隐藏风险、最大回撤的历史教训、尾部风险评估。

{base_rules}

## 量化事实卡（Python 计算，100% 准确）
{fact_card}

## 输出 JSON Schema
```json
{{
  "overall_risk_score": 55,
  "risk_level": "medium_high",
  "diagnosis": [
    {{
      "claim": "年化波动22.4%属于中高风险水平，超过同类平均",
      "confidence": 0.90,
      "evidence": "(年化波动率=22.4%, 下行波动率=15.1%)",
      "sentiment": "negative"
    }}
  ],
  "key_risk": "极端行情每日VaR亏损可达2.8%，连续大跌可能触发连锁反应",
  "key_opportunity": "最大回撤已完全恢复，当前无水下持仓压力",
  "confidence": 0.82,
  "uncertainties": []
}}
```

内容要求:
- diagnosis: 3-5条
- overall_risk_score: 0-100, 0=极低风险, 100=极高风险
- risk_level: low/medium/medium_high/high/extreme
"""


VALUE_VIEW_PROMPT = """你是基金价值面（性价比）分析师。你的任务是评估一只基金的**风险调整后收益与投资价值**。

角色: 你关注的是"这个风险划不划算"。你把收益和风险放在天平两端，Sharpe/Sortino/Calmar 是你最关心的指标。

{base_rules}

## 量化事实卡（Python 计算，100% 准确）
{fact_card}

## 输出 JSON Schema
```json
{{
  "overall_value_score": 60,
  "diagnosis": [
    {{
      "claim": "Sharpe 0.68 < 1.0, 每承担1个单位波动仅获得0.68个单位超额收益",
      "confidence": 0.80,
      "evidence": "(Sharpe=0.68, 年化收益=15.3%, 年化波动=22.4%)",
      "sentiment": "neutral"
    }}
  ],
  "key_risk": "Calmar 0.84, 承担18%回撤才能获得15%年化收益",
  "key_opportunity": "月胜率67%, 亏损月份比例仅33%, 复利优势有利",
  "confidence": 0.75,
  "uncertainties": []
}}
```

内容要求:
- diagnosis: 3-5条
- overall_value_score: 0-100，越高性价比越好
"""


TECHNICAL_VIEW_PROMPT = """你是基金技术面分析师。你的任务是解读**技术指标的信号含义**。

角色: 你关注 RSI、布林带、成交量形态等技术信号。你擅长识别超买超卖、突破和反转信号。你从不单独依赖一个技术指标。

{base_rules}

## 量化事实卡（Python 计算，100% 准确）
{fact_card}

## 输出 JSON Schema
```json
{{
  "overall_tech_score": 65,
  "diagnosis": [
    {{
      "claim": "RSI 58.3 处于中性区间, 无超买超卖信号",
      "confidence": 0.85,
      "evidence": "(RSI14=58.3, 未触及70超买线或30超卖线)",
      "sentiment": "neutral"
    }}
  ],
  "key_risk": "布林带收窄后突破方向不明确",
  "key_opportunity": "RSI中性+MACD金叉, 多头有技术面支撑",
  "confidence": 0.70,
  "uncertainties": ["缺少成交量数据, 部分技术信号(如量价关系)不受支持"]
}}
```

内容要求:
- diagnosis: 3-5条
- overall_tech_score: 0-100, 越高技术面越看多
"""


DEBATE_PROMPT = """你是辩论综合裁判。你的任务是在四个独立分析师给出判断后,**寻找矛盾、裁决分歧、给出综合结论**。

角色: 你不是中和师，而是仲裁者。你不需要平衡各方观点——你需要找出他们谁说得对、哪里矛盾最大、然后给出有明确方向的综合判断。

{base_rules}

## 量化事实卡（Python 计算，100% 准确）
{fact_card}

## 四位分析师的意见
{analyst_opinions}

## 输出 JSON Schema
```json
{{
  "contradictions": [
    {{
      "views": ["trend_view", "value_view"],
      "issue": "趋势面强烈看多(评分75) vs 价值面认为性价比一般(评分60)",
      "severity": "minor",
      "resolution": "两个视角维度不同不直接矛盾。当前阶段趋势确认有效，但风险调整后收益中等。"
    }}
  ],
  "consensus_level": 0.72,
  "consensus_label": "broad_agreement",
  "health_score": 70,
  "health_label": "中等偏上",
  "strengths": [
    "均线多头排列，趋势确认上行 (引用: 净值>全部MA)",
    "回撤已完全恢复，无当前亏损压力 (引用: current_drawdown=0%)"
  ],
  "risks": [
    "Sharpe 0.68 < 1.0, 风险调整后收益一般 (引用: Sharpe=0.68)",
    "MACD柱体缩小，上升动能可能减弱"
  ],
  "action": {{
    "type": "hold",
    "confidence": 0.70,
    "reasoning": "趋势向好但性价比一般。建议维持当前仓位, 如MACD形成死叉再考虑减仓。"
  }},
  "confidence": 0.72,
  "uncertainties": []
}}
```

内容要求:
- contradictions: 显式列出所有视角间的矛盾, severity: minor/moderate/major
- consensus_level: 0-1, 越高观点越一致
- consensus_label: full_consensus(>0.85) / broad_agreement(0.65-0.85) / partial_disagreement(0.40-0.65) / sharp_disagreement(<0.40)
- health_score: 0-100
- strengths/risks: 各3-5条, 每条都引用具体数据
- action.type: buy/hold/sell/reduce/add
- 如果多位分析师方向冲突, 不要强行调和, 降低 confidence 和 consensus_level
"""


PORTFOLIO_PROMPT = """你是组合诊断专家。你的任务是综合分析整个投资组合的健康状况，给出调仓建议。

角色: 你从组合整体视角看问题。你关心分散效果、相关性风险、集中度、有效前沿位置。你不执着于单只基金的涨跌。

{base_rules}

## 组合量化数据（Python 计算，100% 准确）
{portfolio_data}

## 各基金诊断摘要
{fund_summaries}

## 输出 JSON Schema
```json
{{
  "overall_health_score": 68,
  "health_label": "中等偏上",
  "concentration_risk": {{
    "level": "moderate",
    "detail": "前3大持仓占75%, HHI=0.19, 集中度中等偏高。白酒和H3C合计50%, 同属A股市场。",
    "severity": "warning"
  }},
  "correlation_issues": [
    {{
      "pair": ["161725", "164906"],
      "correlation": 0.45,
      "issue": "中度正相关, 在市场下跌时会同时亏损",
      "severity": "info"
    }}
  ],
  "efficient_frontier_analysis": {{
    "current_distance": 2.1,
    "position": "次优 — 距有效前沿2.1%, 同等风险下可获得+1.8%收益",
    "rebalance_direction": "增持000311(从25%→50%), 减持161725(从25%→18%)"
  }},
  "rebalance_suggestions": [
    {{
      "fund_code": "161725",
      "action": "reduce",
      "current_ratio": 25.0,
      "target_ratio": 18.0,
      "change_pct": -7.0,
      "reason": "波动率偏高(22.4%), 有效前沿分析支持降低权重以提高组合Sharpe",
      "evidence": ["年化波动=22.4% vs 组合均值=16%", "5000次蒙特卡洛模拟支持此调整"]
    }}
  ],
  "strengths": ["整体盈利+2.04%", "货币基金占比25%提供流动性", "无基金出现大幅亏损"],
  "weaknesses": ["相关性分散不足", "组合偏离有效前沿", "部分基金与货币基金收益无异"],
  "confidence": 0.68
}}
```

内容要求:
- rebalance_suggestions: 可以空列表 (调仓非必需)
- 调仓建议必须有量化依据, 尤其是有效前沿和相关性数据
- 只对非货币基金提出调仓建议
"""


CROSS_VALID_PROMPT = """你是交叉验证审计员。你的任务是逐条检查整份分析报告，找出:
1. 矛盾 — 不同部分之间的结论冲突
2. 幻觉 — 引用数值无法在原始数据中验证的结论
3. 遗漏 — 重要风险未被讨论
4. 置信度虚高 — 数据不足但结论过于确定的情况

{base_rules}

## 完整分析报告（需审计）
{full_report_text}

## 量化事实卡汇总
{all_fact_cards}

## 输出 JSON Schema
```json
{{
  "issues_found": 2,
  "issues": [
    {{
      "type": "contradiction",
      "location": "value_view vs debate_summary",
      "detail": "价值面诊断为'性价比低'(score=45), 但辩论综合给出了'持有'建议和health_score=65",
      "severity": "moderate",
      "recommendation": "建议将debate_summary.health_score下调至50-55, 或者修正value_view的score"
    }}
  ],
  "overall_audit_pass": true,
  "adjusted_overall_confidence": 0.65,
  "confidence_adjustment_reason": "发现2个矛盾, 降低了综合置信度",
  "warnings": ["多数净值数据不足1年, 长期指标置信度有限"]
}}
```
"""


def build_trend_prompt(qi: QuantIndicators) -> str:
    """Build trend view prompt with fact card."""
    return TREND_VIEW_PROMPT.format(
        base_rules=_base_rules(),
        fact_card=build_fact_card(qi),
    )


def build_risk_prompt(qi: QuantIndicators) -> str:
    return RISK_VIEW_PROMPT.format(
        base_rules=_base_rules(),
        fact_card=build_fact_card(qi),
    )


def build_value_prompt(qi: QuantIndicators) -> str:
    return VALUE_VIEW_PROMPT.format(
        base_rules=_base_rules(),
        fact_card=build_fact_card(qi),
    )


def build_technical_prompt(qi: QuantIndicators) -> str:
    return TECHNICAL_VIEW_PROMPT.format(
        base_rules=_base_rules(),
        fact_card=build_fact_card(qi),
    )


def build_debate_prompt(qi: QuantIndicators, trend: str, risk: str, value: str, technical: str) -> str:
    """Build debate prompt with all 4 analyst opinions."""
    opinions = f"""
## 趋势面分析师
{trend}

## 风险面分析师
{risk}

## 价值面分析师
{value}

## 技术面分析师
{technical}
"""
    return DEBATE_PROMPT.format(
        base_rules=_base_rules(),
        fact_card=build_fact_card(qi),
        analyst_opinions=opinions,
    )


def build_portfolio_prompt(
    portfolio_data: str,
    fund_summaries: str,
) -> str:
    """Build portfolio synthesis prompt."""
    return PORTFOLIO_PROMPT.format(
        base_rules=_base_rules(),
        portfolio_data=portfolio_data,
        fund_summaries=fund_summaries,
    )


def build_cross_validation_prompt(full_report_text: str, all_fact_cards: str) -> str:
    """Build cross-validation prompt."""
    return CROSS_VALID_PROMPT.format(
        base_rules=_base_rules(),
        full_report_text=full_report_text,
        all_fact_cards=all_fact_cards,
    )

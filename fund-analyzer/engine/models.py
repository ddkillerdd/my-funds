"""
FundAnalyzer — Data Models

All dataclass definitions for input/output structures.
Zero dependency on FundAdvisor codebase.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import datetime


# ============================================================
#  INPUT MODELS
# ============================================================

@dataclass
class NavPoint:
    """单个净值数据点"""
    date: str                      # "2026-06-01"
    nav: float                     # 累计净值


@dataclass
class FundHolding:
    """单只基金持仓输入"""
    fund_code: str                 # "161725"
    fund_name: str                 # "招商中证白酒指数C"
    fund_type: str = ""            # "指数型-股票"
    current_mv: float = 0.0        # 当前市值
    cost: float = 0.0              # 持有成本
    mv_ratio: float = 0.0          # 占组合比例 (%)
    is_money_fund: bool = False    # 是否货币基金
    nav_history: List[NavPoint] = field(default_factory=list)
    benchmark_history: Optional[List[NavPoint]] = None  # 基准净值（可选）


@dataclass
class PortfolioInput:
    """完整投资组合输入"""
    holdings: List[FundHolding]
    benchmark_nav_history: Optional[List[NavPoint]] = None  # 组合基准（可选）
    previous_report_id: Optional[int] = None
    previous_reports_json: Optional[List[dict]] = field(default_factory=list)  # 历史报告


# ============================================================
#  QUANT INDICATORS (Ground Truth — 100% Python)
# ============================================================

@dataclass
class TrendIndicators:
    """趋势指标"""
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma120: Optional[float] = None
    current_nav: Optional[float] = None
    ma_deviation_pct: Optional[float] = None       # 当前净值偏离 MA20 的百分比
    ma_status: str = "unknown"                     # above_all/above_short/mixed/below_short/below_all
    trend_strength: Optional[int] = None            # 0-100 趋势强度评分
    trend_direction: str = "unknown"                # up/sideways/down
    price_position_pct: Optional[float] = None      # 在 N 日区间中的位置 %
    consecutive_direction_days: int = 0             # 连续同向天数
    notes: List[str] = field(default_factory=list)


@dataclass
class MacdIndicators:
    """MACD 指标"""
    dif: Optional[float] = None
    dea: Optional[float] = None
    histogram: Optional[float] = None
    signal: str = "unknown"                         # golden_cross_active/death_cross_active/golden_cross_inactive/death_cross_inactive/neutral
    divergence_type: Optional[str] = None           # bullish_divergence/bearish_divergence/none
    notes: List[str] = field(default_factory=list)


@dataclass
class MomentumIndicators:
    """动量指标"""
    rsi_14: Optional[float] = None
    rsi_signal: str = "unknown"                     # overbought/neutral/oversold
    win_rate_20: Optional[float] = None              # 20日上涨天数比例 %
    win_rate_60: Optional[float] = None
    consecutive_up_days: int = 0
    consecutive_down_days: int = 0
    bollinger_upper: Optional[float] = None
    bollinger_mid: Optional[float] = None
    bollinger_lower: Optional[float] = None
    bollinger_position: str = "unknown"              # above_upper/upper_half/lower_half/below_lower
    bollinger_width_pct: Optional[float] = None      # 带宽 %
    notes: List[str] = field(default_factory=list)


@dataclass
class RiskIndicators:
    """风险指标"""
    annual_volatility_pct: Optional[float] = None
    downside_volatility_pct: Optional[float] = None
    volatility_regime: str = "unknown"               # low/medium/high/extreme
    max_drawdown_pct: Optional[float] = None
    max_drawdown_start: Optional[str] = None          # 回撤起始日期
    max_drawdown_end: Optional[str] = None            # 回撤最低点日期
    max_drawdown_recovery_days: Optional[int] = None
    max_drawdown_duration_days: Optional[int] = None
    current_drawdown_pct: Optional[float] = None
    var_95_daily_pct: Optional[float] = None          # 95% Daily VaR
    cvar_95_daily_pct: Optional[float] = None         # 95% Daily CVaR
    ulcer_index: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class ReturnIndicators:
    """收益指标"""
    return_1m_pct: Optional[float] = None
    return_3m_pct: Optional[float] = None
    return_6m_pct: Optional[float] = None
    return_1y_pct: Optional[float] = None
    annual_return_pct: Optional[float] = None
    cumulative_return_pct: Optional[float] = None
    monthly_win_rate: Optional[float] = None          # 月度正收益概率 %
    profit_loss_ratio: Optional[float] = None          # 盈亏比 (涨跌日平均比率)
    best_day_pct: Optional[float] = None
    worst_day_pct: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class EfficiencyIndicators:
    """效率指标"""
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    information_ratio: Optional[float] = None
    omega_ratio: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class BenchmarkIndicators:
    """基准对比指标"""
    excess_return_pct: Optional[float] = None
    beta: Optional[float] = None
    alpha: Optional[float] = None
    tracking_error: Optional[float] = None
    capture_up: Optional[float] = None                # 上行捕获率 %
    capture_down: Optional[float] = None              # 下行捕获率 %
    notes: List[str] = field(default_factory=list)


@dataclass
class PeerBenchmarkData:
    """市场环境/同类对比 (RFC-006 方案D, RFC-009 Market Data Layer)

    Supplies a market reference so "年化波动42%" has context (vs 大盘 18%).
    Populated by engine/market_data.py before analysis; consumed by the
    fact card and screening.
    """
    market_name: str = "沪深300"                 # reference index
    market_annual_volatility: Optional[float] = None
    market_return_6m: Optional[float] = None
    market_current_drawdown: Optional[float] = None
    market_return_1y: Optional[float] = None
    # fund vs market
    vol_ratio: Optional[float] = None            # fund_vol / market_vol
    excess_6m: Optional[float] = None            # fund_6m - market_6m
    # peer ranking (if candidate pool data available)
    peer_sharpe_percentile: Optional[float] = None
    peer_volatility_percentile: Optional[float] = None
    peer_avg_sharpe: Optional[float] = None
    peer_avg_volatility: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class QuantIndicators:
    """单只基金全部量化指标"""
    fund_code: str
    fund_name: str
    fund_type: str
    current_mv: float
    cost: float
    mv_ratio: float
    pnl_amount: float
    pnl_pct: float
    is_money_fund: bool
    nav_history_days: int
    data_quality: str = "unknown"                     # good/adequate/sparse/insufficient

    trend: TrendIndicators = field(default_factory=TrendIndicators)
    macd: MacdIndicators = field(default_factory=MacdIndicators)
    momentum: MomentumIndicators = field(default_factory=MomentumIndicators)
    risk: RiskIndicators = field(default_factory=RiskIndicators)
    returns: ReturnIndicators = field(default_factory=ReturnIndicators)
    efficiency: EfficiencyIndicators = field(default_factory=EfficiencyIndicators)
    benchmark: Optional[BenchmarkIndicators] = None
    # RFC-006 D: 市场环境/同类对比（由 Market Data Layer 填充）
    peer_benchmark: Optional[PeerBenchmarkData] = None

    # 汇总
    all_notes: List[str] = field(default_factory=list)


# ============================================================
#  PORTFOLIO-LEVEL DAYA
# ============================================================

@dataclass
class CorrelationData:
    """组合相关性数据"""
    matrix: List[List[Optional[float]]] = field(default_factory=list)  # 2D array
    labels: List[str] = field(default_factory=list)                      # fund_code list
    avg_pairwise_corr: Optional[float] = None
    high_corr_pairs: List[Dict] = field(default_factory=list)           # [{"pair": [...], "correlation": 0.85}]
    notes: List[str] = field(default_factory=list)


@dataclass
class ConcentrationData:
    """组合集中度"""
    hhi_index: Optional[float] = None
    hhi_label: str = "unknown"                          # low/moderate/high/extreme
    top1_pct: Optional[float] = None
    top3_pct: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class EfficientFrontierData:
    """有效前沿分析"""
    simulations: int = 0
    optimal_sharpe_weights: Dict[str, float] = field(default_factory=dict)
    min_vol_weights: Dict[str, float] = field(default_factory=dict)
    current_position_risk: Optional[float] = None
    current_position_return: Optional[float] = None
    distance_to_frontier_pct: Optional[float] = None    # 当前组合距有效前沿 %
    position_quality: str = "unknown"                    # optimal/near_optimal/suboptimal/poor
    notes: List[str] = field(default_factory=list)


@dataclass
class PortfolioGroundTruth:
    """组合层面量化真相"""
    total_market_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    holding_count: int = 0
    active_count: int = 0
    money_fund_count: int = 0
    data_start_date: Optional[str] = None
    data_end_date: Optional[str] = None
    data_days: int = 0
    overall_data_quality: str = "unknown"                 # good/adequate/sparse/insufficient
    correlation: Optional[CorrelationData] = None
    concentration: Optional[ConcentrationData] = None
    efficient_frontier: Optional[EfficientFrontierData] = None
    notes: List[str] = field(default_factory=list)


# ============================================================
#  VIEW DIAGNOSIS (LLM Output)
# ============================================================

@dataclass
class DiagnosisItem:
    """单条诊断"""
    claim: str
    confidence: float = 0.0                    # 0-1
    evidence: str = ""                          # 强制引用量化指标
    sentiment: str = "neutral"                  # positive/negative/neutral


@dataclass
class ViewDiagnosis:
    """单视角诊断"""
    overall_score: Optional[int] = None          # 0-100
    diagnosis: List[DiagnosisItem] = field(default_factory=list)
    key_risk: str = ""
    key_opportunity: str = ""
    confidence: float = 0.0
    label: str = ""                              # 趋势方向/风险等级等，视角不同含义不同
    uncertainties: List[str] = field(default_factory=list)


@dataclass
class TrendViewDiagnosis(ViewDiagnosis):
    """趋势面诊断"""
    trend_direction: str = "unknown"
    trend_strength_label: str = ""
    pass


@dataclass
class RiskViewDiagnosis(ViewDiagnosis):
    """风险面诊断"""
    risk_level: str = "unknown"
    pass


@dataclass
class ValueViewDiagnosis(ViewDiagnosis):
    """价值面诊断"""
    pass


@dataclass
class TechnicalViewDiagnosis(ViewDiagnosis):
    """技术面诊断"""
    pass


@dataclass
class Contradiction:
    """视角间矛盾"""
    views: List[str] = field(default_factory=list)
    issue: str = ""
    severity: str = "minor"                     # minor/moderate/major
    resolution: str = ""


@dataclass
class DebateSummary:
    """辩论综合结果"""
    contradictions: List[Contradiction] = field(default_factory=list)
    consensus_level: float = 0.0                # 0-1, 越高越一致
    consensus_label: str = "unknown"             # full_consensus/broad_agreement/partial_disagreement/sharp_disagreement
    health_score: int = 0                       # 0-100
    health_label: str = ""
    strengths: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    action: Dict[str, any] = field(default_factory=dict)   # {type, confidence, reasoning}
    confidence: float = 0.0
    uncertainties: List[str] = field(default_factory=list)
    # --- v5: 多模型辩论新增 ---
    model_sources: Dict[str, str] = field(default_factory=dict)  # {view: model_name}
    model_reliability: Dict[str, float] = field(default_factory=dict)  # {model: 0-1}
    conflict_models: List[str] = field(default_factory=list)  # 涉及矛盾最多的模型


@dataclass
class FundDiagnosis:
    """单只基金完整诊断"""
    fund_code: str
    fund_name: str
    ground_truth: QuantIndicators

    trend_view: Optional[TrendViewDiagnosis] = None
    risk_view: Optional[RiskViewDiagnosis] = None
    value_view: Optional[ValueViewDiagnosis] = None
    technical_view: Optional[TechnicalViewDiagnosis] = None
    debate_summary: Optional[DebateSummary] = None

    degraded: bool = False
    degraded_steps: List[str] = field(default_factory=list)


# ============================================================
#  PORTFOLIO DIAGNOSIS (LLM Output)
# ============================================================

@dataclass
class PositionAction:
    """RFC-014 唯一权威动作结构（决策引擎输出，直接进报告+前端）

    action 由 target_weight 与 current_weight 之差派生（asducer 唯一因），
    全量化、幂等、零 LLM 依赖。
    """
    fund_code: str = ""
    action: str = "hold"             # buy/increase/hold/reduce/sell
    action_label: str = "持有"
    current_weight: float = 0.0       # 十进制
    target_weight: float = 0.0        # 十进制
    change_weight_pp: float = 0.0     # 变化百分点 (target-current)*100
    target_weight_pct: float = 0.0    # 目标权重%, 前端展示用
    regime: str = "sideways"
    direction_score: float = 0.0      # L1 [-1,+1]
    momentum_12m: float = 0.0
    vol: float = 0.0                  # 年化波动率%
    max_drawdown: float = 0.0         # 历史最大回撤%
    current_drawdown: float = 0.0     # 当前回撤%
    sharpe: float = 0.0
    decision_source: str = "quant_primary"
    reason: str = ""
    risk_hits: List[str] = field(default_factory=list)  # 命中的风控规则 R1..R6
    friction_held: bool = False       # 是否因换手触发带而保持不动 (R6)

    def to_dict(self) -> Dict[str, any]:
        return {
            "fund_code": self.fund_code,
            "action": self.action,
            "action_label": self.action_label,
            "current_weight": self.current_weight,
            "target_weight": self.target_weight,
            "change_weight_pp": self.change_weight_pp,
            "target_weight_pct": self.target_weight_pct,
            "regime": self.regime,
            "direction_score": self.direction_score,
            "momentum_12m": self.momentum_12m,
            "vol": self.vol,
            "max_drawdown": self.max_drawdown,
            "current_drawdown": self.current_drawdown,
            "sharpe": self.sharpe,
            "decision_source": self.decision_source,
            "reason": self.reason,
            "risk_hits": list(self.risk_hits),
            "friction_held": self.friction_held,
        }


@dataclass
class RebalanceSuggestion:
    """调仓建议"""
    fund_code: str
    action: str = "hold"                        # increase/decrease/hold
    current_ratio: float = 0.0
    target_ratio: float = 0.0
    change_pct: float = 0.0
    reason: str = ""
    evidence: List[str] = field(default_factory=list)


@dataclass
class PortfolioDiagnosis:
    """组合综合诊断"""
    overall_health_score: int = 0
    health_label: str = ""
    concentration_risk: Dict = field(default_factory=dict)
    correlation_issues: List[Dict] = field(default_factory=list)
    efficient_frontier_analysis: Dict = field(default_factory=dict)
    rebalance_suggestions: List[RebalanceSuggestion] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    confidence: float = 0.0
    notes: List[str] = field(default_factory=list)


# ============================================================
#  META & CONFIDENCE
# ============================================================

@dataclass
class GlobalConfidence:
    """全局置信度"""
    overall: float = 0.0
    overall_label: str = "unknown"
    breakdown: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class HistoricalChange:
    """历史变化"""
    fund_code: str
    dimension: str
    previous_value: Optional[float]
    current_value: Optional[float]
    delta: str
    interpretation: str


@dataclass
class HistoricalComparison:
    """历史对比"""
    previous_report_id: Optional[int] = None
    previous_generated_at: Optional[str] = None
    changes: List[HistoricalChange] = field(default_factory=list)
    prediction_accuracy: Optional[str] = None


@dataclass
class Completeness:
    """分析完整度"""
    total_indicators_computed: int = 0
    total_indicators_expected: int = 0
    completeness_pct: float = 0.0
    missing_indicators: List[Dict] = field(default_factory=list)
    data_quality_label: str = "unknown"


@dataclass
class Degradation:
    """降级标记"""
    any_degraded: bool = False
    degraded_steps: List[str] = field(default_factory=list)
    impact: str = "none"                        # none/minor/moderate/severe


# ============================================================
#  OUTPUT REPORT
# ============================================================

@dataclass
class AnalysisReport:
    """完整分析报告"""
    generated_at: str = ""
    analysis_duration_seconds: float = 0.0
    data_duration_seconds: float = 0.0
    model: str = ""
    model_chain: Dict[str, str] = field(default_factory=dict)
    model_roles: Dict[str, str] = field(default_factory=dict)  # {step_label: model_name}
    llm_call_count: int = 0
    llm_failure_count: int = 0
    llm_fallback_count: int = 0

    ground_truth: Optional[PortfolioGroundTruth] = None
    per_fund_diagnosis: List[FundDiagnosis] = field(default_factory=list)
    portfolio_diagnosis: Optional[PortfolioDiagnosis] = None
    confidence: Optional[GlobalConfidence] = None
    completeness: Optional[Completeness] = None
    degradation: Optional[Degradation] = None
    historical_comparison: Optional[HistoricalComparison] = None

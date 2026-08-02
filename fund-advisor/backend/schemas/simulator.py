"""Schemas for the portfolio strategy simulator (RFC-016).

以"盈利"为核心的组合策略回测模块：
- 用户自定义基金 + 初始成本(金额)
- 多窗口点内策略回放, 产出每日组合净值/盈亏趋势
- 盈利判定 + 可执行的优化建议
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict


# ============================================================
#  入参
# ============================================================

class SimulationFundIn(BaseModel):
    """用户自定义的模拟基金 + 初始金额。"""
    fund_code: str = Field(..., description="基金代码")
    fund_name: Optional[str] = None       # 不传则用数据库名称
    amount: float = Field(..., gt=0, description="该基金初始投入金额(元, 即初始成本)")


class SimulationRequest(BaseModel):
    funds: List[SimulationFundIn] = Field(
        default_factory=list,
        description="用户自定义基金与金额; 不传则默认用当前持仓组合(等权总成本)"
    )
    initial_amount: Optional[float] = Field(
        default=None, description="总初始资金(元); 缺省 = Σ各基金amount"
    )
    windows: List[int] = Field(default_factory=lambda: [30, 90, 365])
    warmup: int = Field(default=252, description="信号回看天数")
    target_vol: float = Field(default=0.15, description="波动率目标(0~1)")
    friction_band_pp: float = Field(default=5.0, description="换手触发带(百分点)")
    reference_input: Optional[Dict] = None   # 保留: 后续支持策略对比


# ============================================================
#  出参(渲染所需, 轻量)
# ============================================================

class SimDailyPoint(BaseModel):
    """单日组合净值/盈亏点(供前端趋势图)。"""
    date: str
    total_value: float          # 组合总市值
    holdings_value: float       # 持仓市值
    cash: float                 # 现金
    daily_pnl: float            # 当日盈亏(相对前一交易日)
    cumulative_pnl: float       # 累计盈亏(相对初始投入)
    cumulative_return_pct: float  # 累计收益率%
    actions: Dict[str, str] = Field(default_factory=dict)  # code->action(买/减/卖/持)
    target_weights: Dict[str, float] = Field(default_factory=dict)
    nav: Dict[str, float] = Field(default_factory=dict)  # 每基金当日净值(历史净值走势用)


class SimWindowOut(BaseModel):
    window_days: int
    start_date: str
    end_date: str
    initial_amount: float
    final_value: float
    strategy_return_pct: float
    buy_hold_return_pct: float
    excess_return_pct: float
    strategy_max_drawdown_pct: float
    buy_hold_max_drawdown_pct: float
    is_profitable: bool                    # 该窗口是否盈利(策略收益>0)
    beats_buy_hold: bool                   # 是否跑赢死拿
    per_fund: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    final_weights: Dict[str, float] = Field(default_factory=dict)
    daily: List[SimDailyPoint] = Field(default_factory=list)


class SimAdviceOut(BaseModel):
    """针对具体基金/窗口的可执行优化建议。"""
    level: str = "info"          # success | warning | danger | info
    target: str = ""            # "全部组合" / "基金000311" / "90天窗口"
    message: str = ""
    action: str = ""            # 建议动作(调高target_vol/减仓/换手等)


class SimSummaryOut(BaseModel):
    avg_excess_pct: float
    best_excess_pct: float
    worst_excess_pct: float
    profitable_windows: int
    total_windows: int
    overall_profitable: bool        # 整体能否盈利(多窗口多数正超额或平均正超额)
    profit_confidence: str          # high | medium | low  盈利可信度
    verdict: str                    # 一句话判定


class SimulationResponse(BaseModel):
    generated_at: str = ""
    duration_seconds: float = 0.0
    initial_amount: float = 0.0
    initial_weights: Dict[str, float] = Field(default_factory=dict)
    target_vol: float = 0.15
    warmup: int = 252
    windows: Dict[str, SimWindowOut] = Field(default_factory=dict)   # key=window_days
    summary: SimSummaryOut = Field(default_factory=SimSummaryOut)
    advice: List[SimAdviceOut] = Field(default_factory=list)
    funds_used: List[Dict] = Field(default_factory=list)   # code/name/amount/history_days
    disclaimer: str = "模拟采用理想化执行(无滑点/费率/当日即时), 侧重验证信号方向, 非精确投资收益。仅供参考, 不构成投资建议。"


class SimFundOptionOut(BaseModel):
    """前端下拉可选基金。"""
    fund_code: str
    fund_name: str
    latest_nav: Optional[float] = None
    nav_days: int = 0
    can_backtest: bool = True    # 历史是否 ≥210天(约1年)可回测

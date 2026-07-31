"""
FundAnalyzer — Entry Timing Engine (RFC-007)

Pure-Python quantitative timing recommendation. NO LLM dependency for scoring
(LLM only adds a human-readable summary, handled by caller if desired).

Integrates 6 timing schools into an explainable 0-100 timing_score:

  估值估值 (valuation)   → Phase C (needs Market Data Layer) — weight 0.25
  技术 (technical)       → MA/RSI/MACD/bollinger       — weight 0.30
  趋势 (trend)           → reuse TrendIndicators        — weight 0.20
  回撤位置 (drawdown）   → current vs max drawdown      — weight 0.15
  情绪 (sentiment)       → optional, Phase C            — weight 0.10 (default 0)

Output:
  EntryRecommendation with timing_score, window, factor breakdown, DCA plan,
  and a hard risk gate (never recommend heavy one-shot entry at high risk).

Server-friendly: all NumPy-free vector math via Python lists / reused quant
indicators. Peak memory <50MB even on 1k-day history.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .models import QuantIndicators, NavPoint


# ============================================================
#  OUTPUT MODELS (RFC-007 section 五)
# ============================================================

@dataclass
class TimingFactor:
    """Single factor within the timing score."""
    name: str                 # 估值/技术/趋势/回撤位置/情绪
    score: float              # 0-100
    signal: str               # bullish/neutral/bearish
    evidence: str             # concrete numeric citation
    weight: float             # 0-1, fraction of total
    available: bool = True    # False when data missing (weight re-normalized)


@dataclass
class DCARecommendation:
    """定投计划建议 (RFC-007 3.6)"""
    enabled: bool = False
    method: str = ""          # 均线成本法 / 估值定投法
    frequency: str = "周"      # 周/双周/月
    base_amount_pct: float = 0.0    # 每次占可投预算的 %
    note: str = ""


@dataclass
class EntryRecommendation:
    """Complete timing recommendation for a fund."""
    fund_code: str
    fund_name: str
    timing_score: float = 50.0     # 0-100
    window: str = "wait"           # now_entry/staged_entry/wait/avoid
    factors: List[TimingFactor] = field(default_factory=list)
    dca: Optional[DCARecommendation] = None
    risk_gate: Optional[Dict] = field(default_factory=dict)  # {blocked, reason, cap_ratio}
    confidence: float = 0.5
    ai_summary: str = ""           # optional LLM one-liner (caller fills)
    data_quality: str = "unknown"
    notes: List[str] = field(default_factory=list)


# ============================================================
#  WEIGHTS (RFC-007 section 二)
# ============================================================
BASE_WEIGHTS = {
    "valuation": 0.25,
    "technical": 0.30,
    "trend": 0.20,
    "drawdown": 0.15,
    "sentiment": 0.10,
}
# When a factor is unavailable, weights re-normalize over the available set.
AVAILABLE_NAV_FACTORS = ["technical", "trend", "drawdown"]  # Phase B pure-NAV


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


def _pct(x) -> float:
    """Safely coerce a pct value or None to float."""
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


# ============================================================
#  FACTOR CALCULATORS
# ============================================================

def technical_score(qi: QuantIndicators) -> TimingFactor:
    """Phase B — six-factor technical scoring (RFC-007 3.2).

    Source: reused quant indicators (MA/RSI/MACD/bollinger). 0-100.
    """
    raw = 0.0
    evidence = []
    t, mo, m = qi.trend, qi.momentum, qi.macd

    # 1. MA arrangement (0-24 pts), reuse ma_status for direction
    if t and t.ma_status:
        if t.ma_status == "above_all":
            raw += 24
        elif t.ma_status in ("above_short", "mixed"):
            raw += 12
        evidence.append(f"MA排列={t.ma_status}")

    # 2. Price vs MA20 deviation (0-12 pts; penalty for excessive stretch)
    dev = _pct(t.ma_deviation_pct) if t else 0.0
    if -5.0 <= dev <= 5.0:
        raw += 12
    elif 5.0 < dev <= 10.0:
        raw += 6
    elif -10.0 <= dev < -5.0:
        raw += 9
    else:  # extreme deviation — cool-off
        raw += 3
    evidence.append(f"偏离MA20={dev:.1f}%")

    # 3. RSI (0-20 pts)
    rsi = _pct(mo.rsi_14) if mo else 50.0
    if 40 <= rsi <= 60:
        raw += 20
    elif 60 < rsi <= 70:
        raw += 10
    elif 30 <= rsi < 40:
        raw += 16
    elif rsi > 70:
        raw += 4
    else:  # rsi < 30 oversold — contrarian buy zone
        raw += 12
    evidence.append(f"RSI14={rsi:.1f}")

    # 4. MACD (0-16 pts)
    if m and m.signal:
        if m.signal == "golden_cross_active":
            raw += 16
        elif m.signal == "golden_cross_inactive":
            raw += 10
        elif m.signal == "death_cross_inactive":
            raw += 6
        elif m.signal == "death_cross_active":
            raw += 2
        else:
            raw += 8
        evidence.append(f"MACD={m.signal}")

    # 5. Drawdown position within trend (0-12 pts) — higher release = safer
    dd = abs(_pct(qi.risk.current_drawdown_pct)) if qi.risk else 0.0
    max_dd = abs(_pct(qi.risk.max_drawdown_pct)) if qi.risk else 0.0
    if max_dd > 0:
        release = dd / max_dd  # 0=floor, 1=peak
        raw += 12 if release < 0.3 else 8 if release < 0.6 else 4
        evidence.append(f"回撤释放比例={release:.0%}")
    else:
        raw += 6

    # 6. Consecutive days (0-16 pts) — overextended rally penalized
    up = (mo.consecutive_up_days or 0) if mo else 0
    down = (mo.consecutive_down_days or 0) if mo else 0
    if up >= 5:
        raw += 2          # chasing risk
        evidence.append(f"连涨{up}天(追高风险)")
    elif down >= 5:
        raw += 14         # oversold bounce potential
        evidence.append(f"连跌{down}天(超跌布局)")
    else:
        raw += 8
        evidence.append(f"连涨{up}天/连跌{down}天")

    score = _clamp(raw * 100.0 / 80.0)
    signal = "bullish" if score >= 60 else "bearish" if score <= 40 else "neutral"
    return TimingFactor(
        name="技术", score=round(score, 1), signal=signal,
        evidence="; ".join(evidence), weight=BASE_WEIGHTS["technical"],
    )


def trend_factor(qi: QuantIndicators) -> TimingFactor:
    """Phase B — trend direction & strength (RFC-007 3.3). Reuse TrendIndicators."""
    score = 50.0
    evidence = []
    t = qi.trend
    if t and t.trend_direction:
        if t.trend_direction == "up":
            score = 55.0 + _pct(t.trend_strength) * 0.45  # up to 100
            evidence.append(f"趋势方向={t.trend_direction}")
        elif t.trend_direction == "down":
            score = 45.0 - _pct(t.trend_strength) * 0.45  # down to 0
            evidence.append(f"趋势方向={t.trend_direction}(不接飞刀)")
        else:
            score = 50.0
            evidence.append("趋势方向=sideways")
        if t.trend_strength is not None:
            evidence.append(f"强度={t.trend_strength}")
    if not evidence:
        evidence.append("趋势数据不足")

    score = _clamp(score)
    signal = "bullish" if score >= 60 else "bearish" if score <= 40 else "neutral"
    return TimingFactor(
        name="趋势", score=round(score, 1), signal=signal,
        evidence="; ".join(evidence), weight=BASE_WEIGHTS["trend"],
    )


def drawdown_factor(qi: QuantIndicators) -> TimingFactor:
    """Phase B — drawdown position (RFC-007 3.5).

    risk_pos = 1 - (current_dd / max_dd): 1=at peak (chase risk), 0=at floor.
    We score SAFETY for entry so the "safe to buy" score rises when drawdown
    has released materially but not panic-continuously.
    """
    evidence = []
    dd = abs(_pct(qi.risk.current_drawdown_pct)) if qi.risk else 0.0
    max_dd = abs(_pct(qi.risk.max_drawdown_pct)) if qi.risk else 0.0
    if max_dd <= 0:
        return TimingFactor(
            name="回撤位置", score=50.0, signal="neutral",
            evidence="最大回撤数据不足", weight=BASE_WEIGHTS["drawdown"],
        )

    risk_pos = _clamp(1.0 - (dd / max_dd))  # 0..1
    evidence.append(f"当前回撤={dd:.1f}% 历史最大={max_dd:.1f}% 释放={risk_pos:.0%}")

    if risk_pos < 0.3:
        score = 80.0    # deep in drawdown — staged/batch entry zone
        signal = "bullish"
        evidence.append("深坑区，可分批买入")
    elif risk_pos < 0.6:
        score = 60.0    # mid — neutral, DCA suitable
        signal = "neutral"
        evidence.append("中部区域，适合定投")
    elif risk_pos < 0.85:
        score = 40.0    # near highs — some chase risk
        signal = "bearish"
        evidence.append("接近阶段高点，追高需谨慎")
    else:
        score = 20.0    # at/near peak
        signal = "bearish"
        evidence.append("处于高位，追高风险大")

    return TimingFactor(
        name="回撤位置", score=round(score, 1), signal=signal,
        evidence="; ".join(evidence), weight=BASE_WEIGHTS["drawdown"],
    )


def sentiment_factor() -> TimingFactor:
    """Phase C stub — returns neutral/unavailable. Weight=0 at this stage."""
    return TimingFactor(
        name="情绪", score=50.0, signal="neutral",
        evidence="情绪数据源(Phase C)未接入, 权重置0", weight=0.0, available=False,
    )


def valuation_factor(qi: QuantIndicators) -> Optional[TimingFactor]:
    """Phase C — valuation percentile from Market Data Layer.

    If Market Data Layer provides a valuation_percentile (0-100, low=cheap),
    use it; otherwise return None (weight re-normalized away).
    """
    # Read from a lightweight attribute the Market Data Layer sets on qi.
    percentile = getattr(qi, "_valuation_percentile", None)
    if percentile is None:
        return None
    p = _clamp(float(percentile))
    if p <= 20:
        score, sig = 85.0, "bullish"
        ev = f"估值分位{p:.0f}%(低估区)"
    elif p <= 40:
        score, sig = 70.0, "bullish"
        ev = f"估值分位{p:.0f}%(偏低区)"
    elif p <= 60:
        score, sig = 55.0, "neutral"
        ev = f"估值分位{p:.0f}%(中性区)"
    elif p <= 80:
        score, sig = 35.0, "bearish"
        ev = f"估值分位{p:.0f}%(偏高区)"
    else:
        score, sig = 15.0, "bearish"
        ev = f"估值分位{p:.0f}%(高估区)"
    return TimingFactor(
        name="估值", score=score, signal=sig, evidence=ev,
        weight=BASE_WEIGHTS["valuation"],
    )


# ============================================================
#  HARD RISK GATE (RFC-007 section 四)
# ============================================================

def risk_gate(qi: QuantIndicators, timing_score: float) -> Dict:
    """Never recommend heavy one-shot entry at high-risk positions."""
    reasons = []
    blocked = False
    cap = 1.0  # default: full suggested ratio allowed

    rsi = _pct(qi.momentum.rsi_14) if qi.momentum else 50.0
    dev = _pct(qi.trend.ma_deviation_pct) if qi.trend else 0.0
    dd = abs(_pct(qi.risk.current_drawdown_pct)) if qi.risk else 0.0
    max_dd = abs(_pct(qi.risk.max_drawdown_pct)) if qi.risk else 0.0

    # Gate 1: overbought + stretched above MA20
    if rsi > 70 and dev > 5.0:
        blocked = True
        cap = 0.0
        reasons.append(f"RSI={rsi:.0f}超买且偏离MA20 {dev:.1f}%，禁止一次性追高")

    # Gate 2: deep ongoing drawdown (index-like) — staged entry only
    if dd > 25.0:
        cap = min(cap, 0.4)
        reasons.append(f"当前回撤{dd:.1f}%较深，建议小额分批而非重仓")

    # Gate 3: valuation overbought (if percentile present)
    vp = getattr(qi, "_valuation_percentile", None)
    if vp is not None and vp > 80 and dev > 5.0:
        blocked = True
        cap = 0.0
        reasons.append(f"估值分位{vp:.0f}%且偏离均线，回避一次性重仓")

    # Gate 4: timing_score very low
    if timing_score < 30:
        reasons.append("择时评分<30，当前不是好的入场窗口")

    if not reasons:
        reasons.append("未触发硬性风控")

    return {
        "blocked": blocked,
        "reasons": reasons,
        "cap_ratio": cap,          # max fraction of suggested ratio to deploy
        "max_oneshot_pct": 25.0,   # fixed single-entry cap
    }


# ============================================================
#  DCA PLANNER (RFC-007 3.6)
# ============================================================

def dca_planner(qi: QuantIndicators, window: str,
                budget_pct: float = 10.0) -> DCARecommendation:
    """Decide DCA plan based on trend/drawdown/valuation."""
    if window == "avoid":
        return DCARecommendation(enabled=False, note="当前避免买入，不启动定投")

    t = qi.trend
    trend_up = t and t.trend_direction == "up"
    dd = abs(_pct(qi.risk.current_drawdown_pct)) if qi.risk else 0.0
    max_dd = abs(_pct(qi.risk.max_drawdown_pct)) if qi.risk else 0.0
    release = (dd / max_dd) if max_dd > 0 else 0.5
    vp = getattr(qi, "_valuation_percentile", None)

    rec = DCARecommendation()

    # 估值定投法: prefer valuation percentile when available
    if vp is not None:
        rec.enabled = True
        rec.method = "估值定投法"
        if vp < 40:
            rec.base_amount_pct = budget_pct * 1.3   # 低位多投
            rec.note = f"估值分位{vp:.0f}%偏低，加大定投金额"
        elif vp < 60:
            rec.base_amount_pct = budget_pct
            rec.note = f"估值分位{vp:.0f}%中性，标准定投"
        else:
            rec.base_amount_pct = budget_pct * 0.6   # 高位少投/停投
            rec.note = f"估值分位{vp:.0f}%偏高，减少定投金额"
    else:
        # 均线成本法 fallback (no valuation): NAV vs MA200 approximated by price position
        rec.enabled = True
        rec.method = "均线成本法"
        if not trend_up or release > 0.7:
            rec.base_amount_pct = budget_pct * 0.6
            rec.note = "趋势偏弱/接近高位，降低定投金额"
        elif release < 0.4:
            rec.base_amount_pct = budget_pct * 1.3
            rec.note = "回撤深坑区，逢跌加码"
        else:
            rec.base_amount_pct = budget_pct
            rec.note = "中性区域，标准定投"

    rec.frequency = "周"
    rec.base_amount_pct = round(rec.base_amount_pct, 1)
    return rec


# ============================================================
#  MAIN ENTRY
# ============================================================

def compute_entry_recommendation(
    qi: QuantIndicators,
    budget_pct: float = 10.0,
    override_valuation_percentile: Optional[float] = None,
) -> EntryRecommendation:
    """Compute a complete entry recommendation for one fund.

    Args:
        qi: computed QuantIndicators for the fund.
        budget_pct: what % of investable budget one DCA step should use (default 10%).
        override_valuation_percentile: optional 0-100 valuation percentile from
            Market Data Layer (Phase C). If provided, valuation factor activates.

    Returns:
        EntryRecommendation (window + scoring + DCA + risk gate).
    """
    if override_valuation_percentile is not None:
        qi._valuation_percentile = override_valuation_percentile

    # 1. Compute available factors (pure NAV always available at Phase B)
    factors: List[TimingFactor] = [
        technical_score(qi),
        trend_factor(qi),
        drawdown_factor(qi),
    ]
    val = valuation_factor(qi)
    sent = sentiment_factor()
    if val is not None:
        factors.append(val)
    factors.append(sent)  # available=False, weight 0

    # 2. Re-normalize weights over available factors
    avail = [f for f in factors if f.available and f.weight > 0]
    total_w = sum(f.weight for f in avail) or 1.0
    normalized = [
        TimingFactor(
            name=f.name, score=f.score, signal=f.signal, evidence=f.evidence,
            weight=round(f.weight / total_w, 4),
        )
        for f in avail
    ]

    # 3. Weighted timing score
    timing_score = _clamp(sum(f.score * f.weight for f in normalized))
    # normalize weights for display rounded
    _norm_sum = sum(f.weight for f in normalized) or 1.0
    for f in normalized:
        f.weight = round(f.weight / _norm_sum, 3)

    # 4. Resolve window
    window = _resolve_window(timing_score, qi)

    # 5. Hard risk gate
    gate = risk_gate(qi, timing_score)
    if gate["blocked"]:
        window = "avoid"

    # 6. DCA plan
    dca = dca_planner(qi, window, budget_pct)

    # 7. Data quality gate
    dq = qi.data_quality if qi.data_quality else "unknown"
    confidence = _clamp(timing_score / 100.0 * (0.9 if dq in ("good", "adequate") else 0.65))

    rec = EntryRecommendation(
        fund_code=qi.fund_code,
        fund_name=qi.fund_name,
        timing_score=round(timing_score, 1),
        window=window,
        factors=normalized,
        dca=dca,
        risk_gate=gate,
        confidence=round(confidence, 2),
        data_quality=dq,
    )

    # Data note
    if dq in ("sparse", "insufficient"):
        rec.notes.append(f"净值数据{dq}，择时信号可靠性降低")
    if qi.nav_history_days and qi.nav_history_days < 60:
        rec.notes.append(f"仅{qi.nav_history_days}天历史，长期均线信号参考性有限")

    if window == "avoid":
        rec.notes.append("已触发硬性风控，建议暂缓一次性买入")
        if gate.get("cap_ratio", 1.0) < 1.0 and not gate.get("blocked"):
            rec.notes.append(f"若必须介入，单笔仓位建议不超过建议仓位的{int(gate['cap_ratio']*100)}%")

    return rec


def _resolve_window(score: float, qi: QuantIndicators) -> str:
    """Map timing score + trend to a window label (RFC-007 3.x)."""
    if score >= 70:
        return "now_entry"
    elif score >= 55:
        return "staged_entry"   # staged/batch entry
    elif score >= 40:
        return "wait"
    else:
        return "avoid"


# Backward-compat alias
timing_score = compute_entry_recommendation

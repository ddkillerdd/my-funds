"""
FundAnalyzer — Fund Screener / 荐基引擎 (RFC-008)

Answer "该买什么 + 为什么适合我 + 配多少" from a candidate pool.

Pipeline (all quantitative, LLM only for final one-liner explanation):
  1. Compute factor scores per candidate (momentum/quality/drawdown/diversify/size/valuation)
  2. Style attribution via index correlation (or volatility-cluster fallback)
  3. Rank by weighted total score
  4. Suggested ratio from diversification + timing window + fixed cap
  5. (caller) optional AI explanation on the ranked facts

Server-friendly: candidates processed one at a time; correlation matrix built
incrementally; peak memory bounded. Missing factors get weight re-normalized.

Design refs (RFC-009 section 4): JoinQuant multi-factor selection, Morningstar
style-box approximation, Fama-French factor rationale, risk-parity allocation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

from .models import NavPoint, FundHolding, QuantIndicators
from .timing import compute_entry_recommendation


# ============================================================
#  OUTPUT MODELS (RFC-008 section 七)
# ============================================================

@dataclass
class ScreenerFactorScore:
    factor: str            # momentum/quality/drawdown/diversify/size/valuation
    value: float
    score: float           # 0-100
    evidence: str
    weight: float


@dataclass
class RecommendedFund:
    fund_code: str
    fund_name: str
    fund_type: str
    total_score: float
    factor_scores: List[ScreenerFactorScore] = field(default_factory=list)
    style_tag: str = "未知"
    correlation_with_portfolio: Optional[float] = None
    suggested_ratio_pct: float = 0.0
    timing_window: str = "wait"          # from RFC-007
    timing_score: float = 50.0
    ai_explanation: str = ""             # caller may fill
    data_quality: str = "unknown"
    disclaimer_note: str = "仅供参考，不构成投资建议"


@dataclass
class ScreenerResult:
    generated_at: str = ""
    candidates_scanned: int = 0
    portfolio_context: Dict = field(default_factory=dict)   # HHI, avg corr, top1
    recommendations: List[RecommendedFund] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    data_quality: str = "unknown"


# ============================================================
#  WEIGHTS (RFC-008 section 三)
# ============================================================
BASE_FACTOR_WEIGHTS = {
    "momentum": 0.18,
    "quality": 0.18,
    "drawdown": 0.13,
    "diversify": 0.18,
    "size": 0.09,
    "valuation": 0.13,
    "timing": 0.11,
}

# Style index mapping for attribution (fund-agnostic proxy)
STYLE_INDEXES = {
    "大盘蓝筹": ["沪深300", "上证50"],
    "中小盘成长": ["中证500", "中证1000"],
    "科技成长": ["创业板指"],
}


class ScreenContext:
    """Carries portfolio state + optional market data into scoring."""

    def __init__(
        self,
        portfolio_navs: Optional[List[List[float]]] = None,      # per existing fund
        portfolio_avg_corr: Optional[float] = None,
        top1_pct: Optional[float] = None,
        style_indexes: Optional[Dict[str, List[Tuple[str, float]]]] = None,
    ):
        self.portfolio_navs = portfolio_navs or []
        self.portfolio_avg_corr = portfolio_avg_corr
        self.top1_pct = top1_pct
        self.style_indexes = style_indexes or {}   # style_name -> [(date,close)]


# ============================================================
#  FACTOR SCORERS (each returns 0-100 + evidence)
# ============================================================

def _pct(x) -> float:
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(x)))


def momentum_score(qi: QuantIndicators) -> Tuple[float, str]:
    """Risk-adjusted momentum across 3m/6m/1y."""
    r3 = _pct(qi.returns.return_3m_pct)
    r6 = _pct(qi.returns.return_6m_pct)
    r1 = _pct(qi.returns.return_1y_pct)
    vol = _pct(qi.risk.annual_volatility_pct) or 1.0
    # risk-adjusted (annualized-ish proxy)
    adj = (r3 + 2 * r6 + 4 * r1) / 7.0 / (vol / 10.0)
    score = _clamp(50 + adj * 8)
    ev = f"3m={r3:.1f}% 6m={r6:.1f}% 1y={r1:.1f}% 波动={vol:.1f}%"
    return score, ev


def quality_score(qi: QuantIndicators) -> Tuple[float, str]:
    """Sharpe/Sortino/Calmar blend (risk-adjusted quality)."""
    sh = _pct(qi.efficiency.sharpe_ratio)
    so = _pct(qi.efficiency.sortino_ratio)
    ca = _pct(qi.efficiency.calmar_ratio)
    score = _clamp(50 + (sh + so * 0.7 + ca * 0.6))
    ev = f"Sharpe={sh:.2f} Sortino={so:.2f} Calmar={ca:.2f}"
    return score, ev


def drawdown_score(qi: QuantIndicators) -> Tuple[float, str]:
    """Max drawdown penalty + recovery speed."""
    max_dd = abs(_pct(qi.risk.max_drawdown_pct))
    current_dd = abs(_pct(qi.risk.current_drawdown_pct))
    score = max(0.0, 100 - max_dd * 2.0)
    ev = f"最大回撤={max_dd:.1f}% 当前回撤={current_dd:.1f}% 恢复={qi.risk.max_drawdown_recovery_days or 'N/A'}天"
    return score, ev


def size_score(detail: Optional[Dict]) -> Tuple[float, str]:
    """Scale optimality (2-500亿 preferred)."""
    if not detail:
        return 50.0, "无规模数据(权重应变小)"
    yi = detail.get("scale_yi")
    if yi is None:
        return 50.0, "规模未知"
    if 2 <= yi <= 500:
        score = _clamp(90 - abs(yi - 50) * 0.08)  # peak near 50亿
        ev = f"规模={yi:.1f}亿(合理区间)"
    elif 0.5 <= yi < 2:
        score = 40.0
        ev = f"规模={yi:.1f}亿(偏小,流动性风险)"
    else:
        score = 30.0
        ev = f"规模={yi:.1f}亿(过大或过小)"
    return score, ev


def valuation_score(qi: QuantIndicators) -> Tuple[float, str]:
    """Valuation percentile (low percentile = cheap = higher score)."""
    vp = getattr(qi, "_valuation_percentile", None)
    if vp is None:
        return 50.0, "无估值数据(权重应变小)"
    score = _clamp(100 - float(vp))
    level = "低估" if vp <= 30 else "中性" if vp <= 60 else "偏高"
    return score, f"估值分位={float(vp):.0f}%({level})"


def diversify_score(
    candidate_navs: List[float],
    portfolio_navs: List[List[float]],
) -> Tuple[Optional[float], str]:
    """Correlation complementarity with the existing portfolio."""
    if not portfolio_navs or len(candidate_navs) < 1:
        return None, "无组合参照(相关性权重失效)"

    corr_sum = 0.0
    n = 0
    for pf in portfolio_navs:
        k = min(len(candidate_navs), len(pf))
        if k < 20:
            continue
        c = candidate_navs[-k:]
        p = pf[-k:]
        c0 = [i for i in range(1, len(c)) if c[i - 1] != 0]
        if len(c0) < 20:
            continue
        rc = [(c[i] - c[i - 1]) / c[i - 1] for i in range(1, len(c))]
        rp = [(p[i] - p[i - 1]) / p[i - 1] for i in range(1, len(p))]
        # Pearson
        try:
            import statistics
            mc, mp = statistics.mean(rc), statistics.mean(rp)
            num = sum((a - mc) * (b - mp) for a, b in zip(rc, rp))
            dc = sum((a - mc) ** 2 for a in rc) ** 0.5
            dp = sum((b - mp) ** 2 for b in rp) ** 0.5
            r = num / (dc * dp) if dc * dp > 0 else 0.0
            corr_sum += max(-1.0, min(1.0, r))
            n += 1
        except Exception as e:
            logger.debug("pearson failed: %s", e)
            continue

    if n == 0:
        return None, "相关计算失败"
    avg_corr = corr_sum / n
    score = _clamp((1.0 - avg_corr) * 100)   # lower corr = higher score
    ev = f"与组合平均相关={avg_corr:.2f}"
    return score, ev


def style_attribution(
    candidate_navs: List[float],
    style_indexes: Dict[str, List[Tuple[str, float]]],
) -> str:
    """Associate fund with a style box via correlation to sector indexes.

    Fallback: classify by volatility/momentum into risk tiers.
    """
    if not candidate_navs or not style_indexes:
        return _style_fallback(candidate_navs)

    best = None
    best_r = -1.0
    for style, series in style_indexes.items():
        idx_close = [c for _, c in series]
        k = min(len(candidate_navs), len(idx_close))
        if k < 30:
            continue
        c = candidate_navs[-k:]
        i = idx_close[-k:]
        rc = [(c[j] - c[j - 1]) / c[j - 1] for j in range(1, len(c)) if c[j - 1] != 0]
        ri = [(i[j] - i[j - 1]) / i[j - 1] for j in range(1, len(i)) if i[j - 1] != 0]
        if len(rc) < 30 or len(ri) < 30:
            continue
        try:
            import statistics
            mc, mp = statistics.mean(rc), statistics.mean(ri)
            num = sum((a - mc) * (b - mp) for a, b in zip(rc, ri))
            dc = sum((a - mc) ** 2 for a in rc) ** 0.5
            dp = sum((b - mp) ** 2 for b in ri) ** 0.5
            r = num / (dc * dp) if dc * dp > 0 else 0.0
            r = max(-1.0, min(1.0, r))
        except Exception:
            continue
        if r > best_r:
            best_r, best = r, style
    return best if best is not None else _style_fallback(candidate_navs)


def _style_fallback(candidate_navs) -> str:
    if not candidate_navs:
        return "未知"
    rets = [candidate_navs[i] / candidate_navs[i - 1] - 1 for i in range(1, len(candidate_navs)) if candidate_navs[i - 1] != 0]
    if not rets:
        return "未知"
    import statistics
    vol = statistics.pstdev(rets) * (252 ** 0.5)
    if vol < 0.12:
        return "稳健/低波动"
    if vol < 0.22:
        return "均衡"
    return "积极/高波动"


# ============================================================
#  MAIN ENTRY
# ============================================================

def screen_funds(
    candidates: List[QuantIndicators],
    ctx: ScreenContext,
    details: Optional[Dict[str, Dict]] = None,     # fund_code -> extract_fund_info
    navs_map: Optional[Dict[str, List[NavPoint]]] = None,  # code -> nav points
    budget_pct: float = 10.0,
    top_n: int = 10,
) -> ScreenerResult:
    """Score and rank a candidate pool.

    Args:
        candidates: computed QuantIndicators for each candidate.
        ctx: portfolio & market context.
        details: {code: extract_fund_info dict} for scale/style.
        navs_map: {code: [NavPoint]} raw NAV series for correlation & style.
            If absent, screener falls back to empty navs (diversify/style degrade).
        budget_pct: base single-position % of investable budget.
        top_n: max recommendations to return.

    Returns:
        ScreenerResult (sorted desc by total_score).
    """
    result = ScreenerResult(candidates_scanned=len(candidates))
    result.portfolio_context = {
        "portfolio_avg_corr": ctx.portfolio_avg_corr,
        "top1_pct": ctx.top1_pct,
    }

    scored: List[RecommendedFund] = []

    for qi in candidates:
        code = qi.fund_code
        detail = (details or {}).get(code) or {}
        nav_list = (navs_map or {}).get(code)
        if nav_list is None:
            nav_list = getattr(qi, "_navs", None) or []
        cand_navs = [p.nav for p in nav_list if p.nav is not None]

        # --- factor primitives ---
        m_score, m_ev = momentum_score(qi)
        q_score, q_ev = quality_score(qi)
        d_score, d_ev = drawdown_score(qi)
        div_score, div_ev = diversify_score(cand_navs, _to_float_series(ctx.portfolio_navs))
        s_score, s_ev = size_score(detail) if detail else (50.0, "无规模数据(权重失效)")
        v_score, v_ev = valuation_score(qi)

        # --- 真择时(引擎 timing): 现在该不该买, 参与总分 + 风控门禁 ---
        # vp 若已有则为估值分位, 传给 timing 激活估值因子
        vp_for_timing = getattr(qi, "_valuation_percentile", None)
        try:
            _trec = compute_entry_recommendation(
                qi,
                budget_pct=budget_pct,
                override_valuation_percentile=vp_for_timing,
            )
            t_window = _trec.window            # now_entry/staged/wait/avoid
            t_score = _trec.timing_score       # 0-100
            t_gate_blocked = bool((_trec.risk_gate or {}).get("blocked"))
            t_evidence = _trec.risk_gate.get("reason") if (_trec.risk_gate and _trec.risk_gate.get("blocked")) else ""
            if not t_evidence:
                t_evidence = "; ".join(
                    f"{f.name}:{f.signal}" for f in _trec.factors if getattr(f, "signal", None)
                )
        except Exception as _e:  # noqa: BLE001
            t_window, t_score, t_gate_blocked, t_evidence = "wait", 50.0, False, f"择时失败:{_e}"

        # available factors (weight re-normalization)
        avail_w = {}
        w = dict(BASE_FACTOR_WEIGHTS)
        if div_score is None:
            w["diversify"] = 0.0
        if not detail:
            w["size"] = 0.0
        vp = getattr(qi, "_valuation_percentile", None)
        if vp is None:
            w["valuation"] = 0.0
        for k, v in w.items():
            if v > 0:
                avail_w[k] = v
        wsum = sum(avail_w.values()) or 1.0

        factor_scores = [
            ScreenerFactorScore("momentum", 0.0, m_score, m_ev, w["momentum"] / wsum),
            ScreenerFactorScore("quality", 0.0, q_score, q_ev, w["quality"] / wsum),
            ScreenerFactorScore("drawdown", 0.0, d_score, d_ev, w["drawdown"] / wsum),
            ScreenerFactorScore("diversify", 0.0,
                                div_score if div_score is not None else 50.0,
                                div_ev, w["diversify"] / wsum),
            ScreenerFactorScore("size", 0.0, s_score, s_ev, w["size"] / wsum),
            ScreenerFactorScore("valuation", 0.0, v_score, v_ev, w["valuation"] / wsum),
            ScreenerFactorScore("timing", 0.0, t_score, t_evidence, w["timing"] / wsum),
        ]

        # weighted total (score × weight; avoid 被门禁拦截 -> 总分压到最低)
        total = 0.0
        for fs in factor_scores:
            total += fs.score * fs.weight
        if t_window in ("avoid",) and t_gate_blocked:
            total = 0.0  # 现在不该买 -> 垫底, 不占推荐名额
        total = round(_clamp(total), 1)

        style = style_attribution(cand_navs, ctx.style_indexes)

        # suggested ratio: base, tweaked by diversification
        ratio = budget_pct
        div_real = next((fs.score for fs in factor_scores if fs.factor == "diversify"), 50.0)
        if div_real > 70:
            ratio *= 1.2
        elif div_real < 30:
            ratio *= 0.7
        ratio = round(min(ratio, 25.0), 1)

        corr = None
        if div_score is not None:
            corr = round(1.0 - div_score / 100.0, 3)  # invert score→correlation

        scored.append(RecommendedFund(
            fund_code=code,
            fund_name=qi.fund_name,
            fund_type=qi.fund_type,
            total_score=total,
            factor_scores=factor_scores,
            style_tag=style,
            correlation_with_portfolio=corr,
            suggested_ratio_pct=ratio,
            data_quality=qi.data_quality,
            timing_window=t_window,
            timing_score=t_score,
        ))

    scored.sort(key=lambda r: r.total_score, reverse=True)
    result.recommendations = scored[:top_n]
    if not scored:
        result.notes.append("无候选评分")
    return result


def _to_float_series(portfolio_navs):
    """Coerce portfolio series (floats or NavPoint) to lists of floats."""
    out = []
    for series in portfolio_navs or []:
        row = []
        for v in series:
            row.append(float(v.nav) if hasattr(v, "nav") else float(v))
        if row:
            out.append(row)
    return out

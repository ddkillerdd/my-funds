"""Tests for the fund screener (RFC-008 / 荐基引擎)."""
import random

import pytest

from engine.models import QuantIndicators, NavPoint
from engine.screener import (
    BASE_FACTOR_WEIGHTS,
    ScreenContext,
    RecommendedFund,
    ScreenerResult,
    diversify_score,
    momentum_score,
    quality_score,
    drawdown_score,
    size_score,
    valuation_score,
    style_attribution,
    _style_fallback,
    screen_funds,
)


def _make_qi(code, name, drift=0.05, vol=0.15, sharpe=1.5, maxdd=15,
             scale_yi=None, vp=None, seed=1):
    qi = QuantIndicators(
        fund_code=code, fund_name=name, fund_type="股票型",
        current_mv=0, cost=0, mv_ratio=0, pnl_amount=0, pnl_pct=0,
        is_money_fund=False, nav_history_days=250, data_quality="good",
    )
    qi.returns.return_3m_pct = drift * 0.5 + 5
    qi.returns.return_6m_pct = drift + 10
    qi.returns.return_1y_pct = drift * 2 + 20
    qi.risk.annual_volatility_pct = vol
    qi.efficiency.sharpe_ratio = sharpe
    qi.efficiency.sortino_ratio = sharpe * 0.8
    qi.efficiency.calmar_ratio = sharpe * 0.6
    qi.risk.max_drawdown_pct = -maxdd
    qi.risk.current_drawdown_pct = -maxdd * 0.5
    qi.risk.max_drawdown_recovery_days = 30
    if vp is not None:
        qi._valuation_percentile = vp
    navs = []
    nav = 1.0
    rnd = random.Random(hash(code) % 9999)
    for _ in range(250):
        nav *= 1 + drift / 300 + rnd.gauss(0, vol / 200)
        navs.append(NavPoint(date="", nav=nav))
    qi._navs = navs
    return qi


# ---------- factor scorers ----------

def test_momentum_score_bounds():
    qi = _make_qi("A", "A")
    s, ev = momentum_score(qi)
    assert 0 <= s <= 100
    assert "3m=" in ev


def test_quality_score_bounds():
    qi = _make_qi("A", "A")
    s, ev = quality_score(qi)
    assert 0 <= s <= 100
    assert "Sharpe" in ev


def test_drawdown_penalizes_deep_drawdown():
    mild = _make_qi("A", "A", maxdd=8)
    deep = _make_qi("B", "B", maxdd=55)
    sm, em = drawdown_score(mild)
    sd, ed = drawdown_score(deep)
    assert sm > sd
    assert "最大回撤" in em and "最大回撤" in ed


def test_size_score_ranges():
    s, ev = size_score({"scale_yi": 50})
    assert s > 70
    assert "亿" in ev
    s2, _ = size_score({"scale_yi": 0.3})
    assert s2 < 50
    s3, _ = size_score({"scale_yi": 900})
    assert s3 < 50


def test_valuation_cheap_scores_high():
    cheap = _make_qi("A", "A", vp=10)
    rich = _make_qi("B", "B", vp=90)
    sc, ev = valuation_score(cheap)
    sr, _ = valuation_score(rich)
    assert sc > sr
    assert "低估" in ev


def test_diversify_rewards_uncorrelated():
    def series(seed):
        rnd = random.Random(seed)
        out, nav = [], 1.0
        for _ in range(250):
            nav *= 1 + 0.0002 + rnd.gauss(0, 0.005)
            out.append(nav)
        return out

    a = series(1)
    b = series(2)
    # self correlation => score ~0
    score_same, _ = diversify_score(a, [a])
    # unrelated => high score
    score_diff, _ = diversify_score(a, [b])
    assert score_same is not None and score_diff is not None
    assert score_same < 5
    assert score_diff > 80


def test_diversify_no_portfolio():
    qi = _make_qi("A", "A")
    s, ev = diversify_score([p.nav for p in qi._navs], [])
    assert s is None
    assert "无组合参照" in ev


def test_style_fallback_classifies():
    assert _style_fallback([]) == "未知"
    qi = _make_qi("A", "A")
    tag = _style_fallback([p.nav for p in qi._navs])
    assert tag in ("稳健/低波动", "均衡", "积极/高波动", "未知")


def test_style_attribution_with_index():
    qi = _make_qi("A", "A")
    navs = [p.nav for p in qi._navs]
    style_idx = {"大盘蓝筹": [(str(i), v) for i, v in enumerate(navs)]}
    tag = style_attribution(navs, style_idx)
    assert tag == "大盘蓝筹"


# ---------- screen_funds ----------

def _build_candidates():
    good = _make_qi("010000", "优质稳定", drift=0.05, vol=0.12,
                    sharpe=1.8, maxdd=8, scale_yi=50, vp=35, seed=1)
    tech = _make_qi("020000", "科技新品", drift=0.10, vol=0.35,
                    sharpe=0.3, maxdd=45, scale_yi=5, vp=80, seed=2)
    bad = _make_qi("030000", "业绩下滑", drift=-0.03, vol=0.40,
                   sharpe=-0.5, maxdd=55, scale_yi=300, vp=90, seed=3)
    return [good, tech, bad], {
        "010000": {"scale_yi": 50},
        "020000": {"scale_yi": 5},
        "030000": {"scale_yi": 300},
    }


def test_screen_ranks_quality_first_without_portfolio():
    cands, dets = _build_candidates()
    res = screen_funds(cands, ScreenContext(), details=dets, top_n=5)
    assert isinstance(res, ScreenerResult)
    assert len(res.recommendations) == 3
    # quality fund should lead when no diversification pull
    assert res.recommendations[0].fund_name == "优质稳定"


def test_screen_punishes_redundancy_with_portfolio():
    cands, dets = _build_candidates()
    # portfolio holds the same good fund -> it becomes redundant
    ctx = ScreenContext(portfolio_navs=[cands[0]._navs])
    res = screen_funds(cands, ctx, details=dets, top_n=5)
    good_rec = next(r for r in res.recommendations if r.fund_name == "优质稳定")
    # correlation approx 1 with portfolio => low diversify score => smaller ratio
    assert good_rec.correlation_with_portfolio is not None
    assert good_rec.correlation_with_portfolio > 0.8
    assert good_rec.suggested_ratio_pct <= 10.0


def test_screen_ratio_capped():
    cands, dets = _build_candidates()
    res = screen_funds(cands, ScreenContext(), details=dets,
                       budget_pct=10, top_n=5)
    for r in res.recommendations:
        assert r.suggested_ratio_pct <= 25.0


def test_screen_weight_renormalization_when_data_missing():
    # no detail, no valuation => size/valuation weights drop out
    cands, _ = _build_candidates()
    for qi in cands:
        qi._valuation_percentile = None
    res = screen_funds(cands, ScreenContext(), details={}, top_n=5)
    rec = res.recommendations[0]
    used = {fs.factor for fs in rec.factor_scores if fs.weight > 0}
    assert "size" not in used
    assert "valuation" not in used
    assert "momentum" in used and "quality" in used and "drawdown" in used
    # weights renormalized to sum ~1
    total_w = sum(fs.weight for fs in rec.factor_scores)
    assert abs(total_w - 1.0) < 0.01


def test_screen_empty_candidates():
    res = screen_funds([], ScreenContext(), top_n=5)
    assert res.recommendations == []
    assert len(res.notes) >= 1


def test_base_weights_loaded():
    assert abs(sum(BASE_FACTOR_WEIGHTS.values()) - 1.0) < 0.01
    assert set(BASE_FACTOR_WEIGHTS) == {
        "momentum", "quality", "drawdown", "diversify", "size", "valuation",
    }

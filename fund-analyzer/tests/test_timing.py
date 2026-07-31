"""Tests for engine.timing — RFC-007 Entry Timing Engine."""

import pytest

from engine.models import QuantIndicators
from engine.timing import (
    compute_entry_recommendation,
    technical_score,
    trend_factor,
    drawdown_factor,
    risk_gate,
    dca_planner,
)


def _qi(code="001", name="测试", rsi=50, ma_status="mixed", dev=0.0,
        macd_sig="neutral", trend_dir="sideways", strength=50,
        dd=5.0, max_dd=20.0, vol=18.0, up=1, down=1, quality="good"):
    qi = QuantIndicators(
        fund_code=code, fund_name=name, fund_type="", current_mv=0, cost=0,
        mv_ratio=0, pnl_amount=0, pnl_pct=0, is_money_fund=False,
        nav_history_days=250, data_quality=quality,
    )
    qi.momentum.rsi_14 = rsi
    qi.trend.ma_status = ma_status
    qi.trend.ma_deviation_pct = dev
    qi.macd.signal = macd_sig
    qi.trend.trend_direction = trend_dir
    qi.trend.trend_strength = strength
    qi.risk.current_drawdown_pct = -dd
    qi.risk.max_drawdown_pct = -max_dd
    qi.risk.annual_volatility_pct = vol
    qi.momentum.consecutive_up_days = up
    qi.momentum.consecutive_down_days = down
    return qi


class TestTechnicalScore:
    def test_overbought_penalized(self):
        qi = _qi(rsi=78, ma_status="above_all", dev=8,
                 macd_sig="death_cross_active", up=6)
        f = technical_score(qi)
        assert f.name == "技术"
        assert 0 <= f.score <= 100
        assert f.evidence

    def test_healthy_midzone(self):
        qi = _qi(rsi=50, ma_status="above_short", dev=2,
                 macd_sig="golden_cross_active", up=2)
        f = technical_score(qi)
        assert f.score > 0

    def test_rsi_window(self):
        assert 0 <= technical_score(_qi(rsi=20)).score <= 100
        assert 0 <= technical_score(_qi(rsi=80)).score <= 100


class TestTrendFactor:
    def test_up_direction(self):
        f = trend_factor(_qi(trend_dir="up", strength=90))
        assert f.signal in ("bullish", "neutral")

    def test_down_direction(self):
        f = trend_factor(_qi(trend_dir="down", strength=80))
        assert f.score < 50


class TestDrawdownFactor:
    def test_floor_release_safe(self):
        # deep drawdown (dd close to max) → release small → staged buy zone
        f = drawdown_factor(_qi(dd=18, max_dd=20))
        assert f.score > 50

    def test_peak_chase_risk(self):
        # near peak (dd small) → release high → chase risk
        f = drawdown_factor(_qi(dd=1, max_dd=20))
        assert f.score < 50

    def test_no_data(self):
        qi = _qi()
        qi.risk.max_drawdown_pct = None
        f = drawdown_factor(qi)
        assert f.score == 50.0


class TestRiskGate:
    def test_overbought_stretch_blocks(self):
        qi = _qi(rsi=78, dev=6, max_dd=20)
        g = risk_gate(qi, timing_score=60)
        assert g["blocked"] is True
        assert g["cap_ratio"] == 0.0

    def test_deep_drawdown_caps(self):
        qi = _qi(dd=26, max_dd=40)
        g = risk_gate(qi, timing_score=55)
        assert g["cap_ratio"] < 1.0

    def test_high_valuation_blocks(self):
        qi = _qi(rsi=60, dev=6, max_dd=20)
        qi._valuation_percentile = 85
        g = risk_gate(qi, timing_score=60)
        assert g["blocked"] is True


class TestDCA:
    def test_cheap_valuation_adds(self):
        qi = _qi()
        qi._valuation_percentile = 30
        d = dca_planner(qi, "staged_entry", budget_pct=10)
        assert d.enabled is True
        assert d.base_amount_pct > 10

    def test_expensive_valuation_reduces(self):
        qi = _qi()
        qi._valuation_percentile = 80
        d = dca_planner(qi, "staged_entry", budget_pct=10)
        assert d.base_amount_pct < 10

    def test_avoid_disables(self):
        d = dca_planner(_qi(), "avoid", budget_pct=10)
        assert d.enabled is False


class TestEntryRecommendation:
    def test_avoid_on_overbought(self):
        r = compute_entry_recommendation(
            _qi(rsi=80, dev=7, max_dd=20, up=6), budget_pct=10,
            override_valuation_percentile=80,
        )
        assert r.window == "avoid"
        assert r.risk_gate["blocked"] is True

    def test_phase_b_no_valuation(self):
        # Pure NAV (Phase B) — no valuation should not crash and DCA falls back
        r = compute_entry_recommendation(
            _qi(rsi=50, ma_status="above_all", trend_dir="up",
                strength=70, dd=6, max_dd=18, up=2),
            budget_pct=10,
        )
        assert r.window in ("now_entry", "staged_entry", "wait")
        assert r.dca.method == "均线成本法" or r.dca.method == "估值定投法"
        # weights normalized to ~1.0
        assert abs(sum(f.weight for f in r.factors) - 1.0) < 0.05

    def test_fields_present(self):
        r = compute_entry_recommendation(_qi(), budget_pct=10)
        assert r.timing_score >= 0 and r.timing_score <= 100
        assert r.factors
        assert isinstance(r.dca, object)
        assert "blocked" in r.risk_gate
        assert r.confidence > 0

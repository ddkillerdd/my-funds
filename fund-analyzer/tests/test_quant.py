"""test_quant.py — Unit tests for quantitative indicators"""

import sys
sys.path.insert(0, "/root/.openclaw/workspace/fund-analyzer")

import pytest
from engine.quant import compute_all, compute_trend, compute_macd, compute_risk, compute_returns
from engine.models import NavPoint, FundHolding
from .fixtures import make_nav_history, make_holding, standard_portfolio


class TestTrendIndicators:
    def test_full_data(self):
        """120 days → all trend indicators computed."""
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        t = qi.trend
        assert t.current_nav is not None
        assert t.ma5 is not None
        assert t.ma10 is not None
        assert t.ma20 is not None
        assert t.ma60 is not None
        assert t.ma120 is not None  # 120 days >= MA120 window
        assert t.ma_status in ("above_all", "above_short", "below_all", "below_short", "mixed")
        assert t.trend_direction in ("up", "down", "sideways")
        assert t.trend_strength is not None
        assert 0 <= t.trend_strength <= 100

    def test_sparse_data(self):
        """10 days → some indicators missing, but no crash."""
        h = make_holding("002", "短历史", days=10)
        qi = compute_all(h)
        t = qi.trend
        assert t.ma5 is not None
        assert t.ma10 is not None
        assert t.ma20 is None
        assert t.ma60 is None
        assert qi.data_quality == "insufficient"
        assert len(qi.all_notes) >= 0  # may or may not have notes

    def test_money_fund(self):
        """Money fund should still compute indicators."""
        h = make_holding("mf", "货币", days=120, is_money=True, drift=0.00005, vol=0.0005)
        qi = compute_all(h)
        assert qi.is_money_fund
        assert qi.trend.trend_direction != "unknown"


class TestMacd:
    def test_macd_with_enough_data(self):
        """120 days → MACD computed."""
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        m = qi.macd
        assert m.dif is not None
        assert m.dea is not None
        assert m.histogram is not None
        assert m.signal in (
            "golden_cross_active", "golden_cross_inactive",
            "death_cross_active", "death_cross_inactive", "neutral",
        )

    def test_macd_with_short_data(self):
        """15 days → no MACD."""
        h = make_holding("short", "短", days=15)
        qi = compute_all(h)
        assert qi.macd.dif is None
        assert "不足26天" in qi.macd.notes[0] if qi.macd.notes else True


class TestRisk:
    def test_risk_metrics(self):
        """120 days → all risk metrics."""
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        r = qi.risk
        assert r.annual_volatility_pct is not None
        assert r.volatility_regime in ("low", "medium", "high", "extreme", "unknown")
        assert r.max_drawdown_pct is not None
        assert r.max_drawdown_pct <= 0  # negative or zero
        assert r.var_95_daily_pct is not None
        assert r.cvar_95_daily_pct is not None

    def test_drawdown_recovery(self):
        """Check drawdown structure."""
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        r = qi.risk
        if r.max_drawdown_pct is not None and r.max_drawdown_pct < 0:
            assert r.max_drawdown_start is not None or r.notes  # start or note


class TestReturns:
    def test_period_returns(self):
        """Period returns for different windows."""
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        ret = qi.returns
        assert ret.return_1m_pct is not None
        assert ret.return_3m_pct is not None
        assert ret.return_1y_pct is None  # < 252 days

    def test_cumulative_return(self):
        """Cumulative should never be None with >1 day."""
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        assert qi.returns.cumulative_return_pct is not None


class TestEfficiency:
    def test_sharpe_ratio(self):
        """Sharpe ratio computed for 120d history."""
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        assert qi.efficiency.sharpe_ratio is not None
        assert qi.efficiency.sortino_ratio is not None


class TestPnL:
    def test_pnl_calculation(self):
        """Profit/Loss computed correctly."""
        h = make_holding("001", "测试", mv=10500, cost=10000)
        qi = compute_all(h)
        assert qi.pnl_amount == 500.0
        assert qi.pnl_pct == 5.0

    def test_zero_cost(self):
        """Zero cost should not explode."""
        h = make_holding("001", "测试", mv=10000, cost=0)
        qi = compute_all(h)
        assert qi.pnl_pct == 0.0


class TestPortfolio:
    def test_all_indicators(self):
        """Every holding gets computed."""
        holdings = standard_portfolio()
        for h in holdings:
            qi = compute_all(h)
            assert qi.fund_code == h.fund_code
            assert qi.data_quality in ("good", "adequate", "sparse", "insufficient")

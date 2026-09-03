"""test_portfolio_quant.py — Unit tests for portfolio-level quant"""

import pytest
from engine.portfolio_quant import correlation_matrix, concentration, efficient_frontier
from engine.models import FundHolding, NavPoint
from .fixtures import standard_portfolio, make_holding


class TestCorrelation:
    def test_matrix_shape(self):
        """Matrix matches number of funds."""
        holdings = standard_portfolio()
        corr = correlation_matrix(holdings)
        assert len(corr.labels) >= 3  # 3 active + 1 money fund (but money excluded)
        for row in corr.matrix:
            assert len(row) == len(corr.labels)

    def test_diagonal_is_one(self):
        """Diagonal correlation is always 1.0."""
        holdings = standard_portfolio()
        corr = correlation_matrix(holdings)
        for i in range(len(corr.labels)):
            assert corr.matrix[i][i] == 1.0

    def test_matrix_is_symmetric(self):
        """Correlation matrix is symmetric."""
        holdings = standard_portfolio()
        corr = correlation_matrix(holdings)
        n = len(corr.labels)
        for i in range(n):
            for j in range(n):
                assert corr.matrix[i][j] == corr.matrix[j][i]

    def test_single_fund(self):
        """Single fund → empty correlation."""
        h = [make_holding("001", "单一")]
        corr = correlation_matrix(h)
        assert corr.avg_pairwise_corr is None


class TestConcentration:
    def test_equal_weights(self):
        """4 equal-weight holdings → HHI ~ 0.25."""
        holdings = standard_portfolio()
        conc = concentration(holdings)
        assert conc.hhi_index is not None
        assert 0.2 < conc.hhi_index < 0.3  # ~0.25
        assert conc.top1_pct == 25.0

    def test_single_holding(self):
        """Single holding → HHI = 1.0."""
        h = [make_holding("001", "全部")]
        conc = concentration(h)
        assert conc.hhi_index == 1.0
        assert conc.top1_pct == 100.0

    def test_empty(self):
        """Empty → no crash."""
        conc = concentration([])
        assert "无持仓" in conc.notes[0] if conc.notes else True


class TestEfficientFrontier:
    def test_simulation_runs(self):
        """Monte Carlo runs and returns weights."""
        holdings = standard_portfolio()
        ef = efficient_frontier(holdings)
        assert ef.simulations > 0
        assert len(ef.optimal_sharpe_weights) >= 3
        assert len(ef.min_vol_weights) >= 3
        assert sum(ef.optimal_sharpe_weights.values()) == pytest.approx(1.0, abs=0.01)
        assert sum(ef.min_vol_weights.values()) == pytest.approx(1.0, abs=0.01)

    def test_current_position(self):
        """Current portfolio has risk/return metrics."""
        holdings = standard_portfolio()
        ef = efficient_frontier(holdings)
        assert ef.current_position_risk is not None
        assert ef.current_position_return is not None
        assert ef.position_quality in ("optimal", "near_optimal", "suboptimal", "poor")

    def test_few_funds(self):
        """Less than 2 active funds → notes but no crash."""
        h = [make_holding("001", "单个")]
        ef = efficient_frontier(h)
        assert len(ef.notes) > 0
        assert len(ef.optimal_sharpe_weights) == 0

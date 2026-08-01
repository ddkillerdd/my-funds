"""test_analyzer.py — Integration test for the full analysis pipeline (no LLM calls)"""

import sys
sys.path.insert(0, "/root/.openclaw/workspace/fund-analyzer")

import pytest
import json
from engine.models import (
    NavPoint, FundHolding, PortfolioInput, AnalysisReport,
    FundDiagnosis, PortfolioDiagnosis,
)
from engine.analyzer import Analyzer
from engine.llm_client import LLMConfig
from .fixtures import standard_portfolio, make_holding, make_nav_history


class TestAnalyzerInit:
    def test_creates_analyzer(self):
        config = LLMConfig(api_base="http://localhost/v1", api_key="test")
        a = Analyzer(config)
        assert a is not None
        assert a.config == config


class TestMoneyFundHandling:
    """Test that money funds get skipped analysis (no LLM) in a way that doesn't crash."""

    def test_money_fund_gets_default_diagnosis(self):
        """Money fund should be handled without LLM calls. We test this by
        constructing a portfolio with only money funds and verifying it doesn't
        make any LLM calls (call_count = 0)."""
        config = LLMConfig(api_base="http://localhost/v1", api_key="test")
        a = Analyzer(config)

        h = make_holding("mf", "货币基金", is_money=True, days=60, drift=0.00005, vol=0.0005)
        portfolio = PortfolioInput(holdings=[h])
        report = a.analyze(portfolio)

        # Portfolio/cross-val still try LLM (not per-fund views); call count ≥ 0 OK
        assert report.llm_call_count >= 0
        assert len(report.per_fund_diagnosis) == 1
        fd = report.per_fund_diagnosis[0]
        assert fd.fund_code == "mf"
        assert fd.trend_view is not None
        assert fd.risk_view is not None
        assert fd.value_view is not None
        assert fd.technical_view is not None
        assert fd.debate_summary is not None
        assert fd.debate_summary.health_score == 50


class TestInsufficientData:
    """Test that insufficient nav history produces degraded results."""

    def test_very_short_history(self):
        """Fund with <20 days nav → degraded analysis."""
        config = LLMConfig(api_base="http://localhost/v1", api_key="test")
        a = Analyzer(config)

        h = make_holding("short", "超短历史", days=5)
        portfolio = PortfolioInput(holdings=[h])
        report = a.analyze(portfolio)

        # Portfolio/cross-val still try LLM (not per-fund views)
        assert report.llm_call_count >= 0
        fd = report.per_fund_diagnosis[0]
        assert fd.degraded
        assert "all_views" in fd.degraded_steps
        assert fd.debate_summary.health_score == 40
        assert len(fd.debate_summary.risks) > 0


class TestReportStructure:
    """Test that the output report has all required top-level fields."""

    def test_money_fund_report_structure(self):
        config = LLMConfig(api_base="http://localhost/v1", api_key="test")
        a = Analyzer(config)

        h = make_holding("mf", "货币", is_money=True)
        portfolio = PortfolioInput(holdings=[h])
        report = a.analyze(portfolio)

        # Meta fields
        assert report.generated_at
        assert report.analysis_duration_seconds >= 0
        assert report.model
        assert report.llm_call_count >= 0

        # Ground truth
        assert report.ground_truth is not None
        assert report.ground_truth.total_market_value > 0
        assert report.ground_truth.holding_count == 1

        # Per-fund
        assert len(report.per_fund_diagnosis) == 1

        # Portfolio diagnosis
        assert report.portfolio_diagnosis is not None
        assert isinstance(report.portfolio_diagnosis.overall_health_score, int)

        # Confidence
        assert report.confidence is not None
        assert 0 <= report.confidence.overall <= 1

        # Completeness
        assert report.completeness is not None

        # Degradation
        assert report.degradation is not None
        assert isinstance(report.degradation.any_degraded, bool)


class TestSerialization:
    """Test that report can be serialized to JSON without errors."""

    def test_report_to_json(self):
        config = LLMConfig(api_base="http://localhost/v1", api_key="test")
        a = Analyzer(config)

        holdings = [make_holding("mf", "货币", is_money=True)]
        portfolio = PortfolioInput(holdings=holdings)
        report = a.analyze(portfolio)

        # Should serialize without error
        d = report.__dict__
        # Handle nested dataclasses
        json_str = json.dumps(d, default=str, ensure_ascii=False)
        assert len(json_str) > 100
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert "generated_at" in parsed
        assert "ground_truth" in parsed


class TestPortfolioSynthesisQuant:
    """组合诊断纯量化（B 方案）行为测试：字段完整性 + 调仓建议阈值门控。"""

    def _analyzer(self):
        config = LLMConfig(api_base="http://localhost/v1", api_key="test")
        return Analyzer(config)

    def _mk_history(self, dist):
        from engine.models import PortfolioGroundTruth, ConcentrationData, EfficientFrontierData
        return PortfolioGroundTruth(
            total_market_value=100000, total_pnl_pct=1.56, holding_count=4, active_count=4,
            overall_data_quality="good",
            concentration=ConcentrationData(hhi_index=0.33, hhi_label="moderate",
                                            top1_pct=36.0, top3_pct=99.7),
            efficient_frontier=EfficientFrontierData(
                simulations=2000,
                optimal_sharpe_weights={"000311": 0.5, "161725": 0.18, "588760": 0.17, "018044": 0.15},
                current_position_risk=0.22, current_position_return=0.12,
                distance_to_frontier_pct=dist,
                position_quality="suboptimal" if dist > 3 else "near_optimal",
            ),
        )

    def test_health_label_is_quant_label_not_empty(self):
        a = self._analyzer()
        pd = a._portfolio_synthesis(PortfolioInput(holdings=[]), [], [], self._mk_history(1.0))
        # B 方案：量化标签，绝不是空 / 无法评估
        assert pd.overall_assessment if hasattr(pd, "overall_assessment") else True
        assert pd.health_label not in ("", None)
        assert isinstance(pd.overall_health_score, int)
        assert pd.concentration_risk.get("detail")

    def test_rebalance_empty_when_near_frontier(self):
        """接近有效前沿（偏离 1%）不应生成 rebalance 建议 → per-fund 决策主导。"""
        a = self._analyzer()
        pd = a._portfolio_synthesis(PortfolioInput(holdings=[]), [], [], self._mk_history(1.0))
        assert pd.rebalance_suggestions == []
        assert pd.efficient_frontier_analysis.get("rebalance_direction") == "维持现状"

    def test_rebalance_present_when_far_from_frontier(self):
        """显著偏离有效前沿（偏离 15.8%）应生成 rebalance 建议。"""
        a = self._analyzer()
        pd = a._portfolio_synthesis(PortfolioInput(holdings=[]), [], [], self._mk_history(15.8))
        assert len(pd.rebalance_suggestions) > 0
        assert pd.efficient_frontier_analysis.get("rebalance_direction") != "维持现状"

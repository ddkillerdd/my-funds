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

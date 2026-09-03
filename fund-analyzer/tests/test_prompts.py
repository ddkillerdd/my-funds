"""test_prompts.py — Unit tests for prompt templates"""

import pytest
from engine.prompts import (
    build_fact_card,
    build_trend_prompt,
    build_risk_prompt,
    build_value_prompt,
    build_technical_prompt,
    build_debate_prompt,
    build_portfolio_prompt,
    build_cross_validation_prompt,
)
from engine.quant import compute_all
from .fixtures import make_holding


class TestFactCard:
    def test_contains_fund_info(self):
        h = make_holding("161725", "招商中证白酒指数C")
        qi = compute_all(h)
        fc = build_fact_card(qi)
        assert "161725" in fc
        assert "招商中证白酒" in fc
        assert "股票型" in fc
        assert "持仓信息" in fc
        assert "均线与趋势" in fc
        assert "MACD" in fc

    def test_nulls_become_na(self):
        """N/A values use 'N/A' not 'None'."""
        h = make_holding("001", "测试", days=10)
        qi = compute_all(h)
        fc = build_fact_card(qi)
        assert "N/A" in fc  # some indicators should be N/A
        assert "None" not in fc

    def test_all_sections_present(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        fc = build_fact_card(qi)
        sections = ["持仓信息", "均线与趋势", "MACD", "动量指标", "风险指标", "收益表现", "效率"]
        for s in sections:
            assert s in fc, f"Missing section: {s}"


class TestViewPrompts:
    def test_trend_prompt(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        p = build_trend_prompt(qi)
        assert "量化事实卡" in p
        assert "output" in p.lower() or "JSON Schema" in p
        assert "核心规则" in p

    def test_risk_prompt(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        p = build_risk_prompt(qi)
        assert "风险面" in p or "risk" in p.lower()
        assert "量化事实卡" in p

    def test_value_prompt(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        p = build_value_prompt(qi)
        assert "性价比" in p or "value" in p.lower()

    def test_technical_prompt(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        p = build_technical_prompt(qi)
        assert "技术面" in p or "technical" in p.lower()


class TestDebatePrompt:
    def test_contains_all_analysts(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        p = build_debate_prompt(qi, "trend_op", "risk_op", "value_op", "tech_op")
        assert "trend_op" in p
        assert "risk_op" in p
        assert "value_op" in p
        assert "tech_op" in p

    def test_contradictions_schema(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        p = build_debate_prompt(qi, "{}", "{}", "{}", "{}")
        assert "contradictions" in p
        assert "consensus_level" in p
        assert "action" in p


class TestPortfolioPrompt:
    def test_contains_data(self):
        p = build_portfolio_prompt("测试数据", "基金摘要")
        assert "测试数据" in p
        assert "基金摘要" in p


class TestCrossValidationPrompt:
    def test_contains_inputs(self):
        p = build_cross_validation_prompt("报告文本", "事实卡")
        assert "报告文本" in p
        assert "事实卡" in p

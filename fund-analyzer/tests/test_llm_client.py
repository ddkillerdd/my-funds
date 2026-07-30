"""test_llm_client.py — Unit tests for LLM client and fallbacks (no actual API calls)"""

import sys
sys.path.insert(0, "/root/.openclaw/workspace/fund-analyzer")

import pytest
import json
from engine.llm_client import (
    LLMConfig,
    parse_json_response,
    validate_diagnosis_json,
    fallback_trend_diagnosis,
    fallback_risk_diagnosis,
    fallback_value_diagnosis,
    fallback_technical_diagnosis,
    fallback_debate,
)
from engine.quant import compute_all
from .fixtures import make_holding


class TestParseJsonResponse:
    def test_pure_json(self):
        data = parse_json_response('{"a": 1, "b": 2}')
        assert data == {"a": 1, "b": 2}

    def test_code_fenced_json(self):
        data = parse_json_response('```json\n{"x": "y"}\n```')
        assert data == {"x": "y"}

    def test_markdown_code_block(self):
        data = parse_json_response('Some text\n```\n{"key": [1,2,3]}\n```')
        assert data == {"key": [1, 2, 3]}

    def test_json_with_trailing_text(self):
        data = parse_json_response('{"result": true}\nHere is some explanation.')
        assert data == {"result": True}

    def test_nested_braces(self):
        data = parse_json_response('{"outer": {"inner": [{"a": 1}]}}')
        assert data == {"outer": {"inner": [{"a": 1}]}}

    def test_invalid_json(self):
        data = parse_json_response("not json at all")
        assert data is None

    def test_empty_string(self):
        assert parse_json_response("") is None
        assert parse_json_response(None) is None

    def test_array_json(self):
        data = parse_json_response('[1, 2, 3]')
        assert data == [1, 2, 3]


class TestValidateDiagnosisJson:
    def test_valid_trend(self):
        errors = validate_diagnosis_json({
            "overall_trend_score": 75,
            "diagnosis": [{"claim": "test", "confidence": 0.8}],
            "key_risk": "risk",
            "key_opportunity": "opp",
            "confidence": 0.8,
        }, "trend")
        # diagnosis present and has items → valid
        assert len([e for e in errors if "empty" in e]) == 0

    def test_empty_diagnosis(self):
        errors = validate_diagnosis_json({
            "diagnosis": [],
            "confidence": 0.8,
        }, "trend")
        assert any("empty" in e for e in errors)

    def test_debate_missing_field(self):
        errors = validate_diagnosis_json({
            "health_score": 70,
        }, "debate")
        assert any("missing" in e or "contradictions" in e for e in errors)


class TestFallbacks:
    def test_fallback_trend(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        result = fallback_trend_diagnosis(qi)
        assert "overall_trend_score" in result
        assert "diagnosis" in result
        assert len(result["diagnosis"]) >= 1
        assert "evidence" in result["diagnosis"][0]

    def test_fallback_risk(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        result = fallback_risk_diagnosis(qi)
        assert "overall_risk_score" in result
        assert "risk_level" in result

    def test_fallback_value(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        result = fallback_value_diagnosis(qi)
        assert "overall_value_score" in result

    def test_fallback_technical(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        result = fallback_technical_diagnosis(qi)
        assert "overall_tech_score" in result

    def test_fallback_debate(self):
        h = make_holding("001", "测试", days=120)
        qi = compute_all(h)
        result = fallback_debate(
            qi,
            {"overall_trend_score": 70},
            {"overall_risk_score": 40},
            {"overall_value_score": 60},
            {"overall_tech_score": 65},
        )
        assert "health_score" in result
        assert "action" in result
        assert result["action"]["type"] == "hold"


class TestLLMConfig:
    def test_default_config(self):
        config = LLMConfig(api_base="http://localhost:8443/v1", api_key="test-key")
        assert config.primary_model == "nvidia/nvidia-nemotron-nano-9b-v2"
        assert len(config.fallback_models) >= 1
        assert config.default_timeout == 60.0

    def test_custom_config(self):
        config = LLMConfig(
            api_base="http://custom/v1",
            api_key="key",
            primary_model="custom-model",
            fallback_models=["fallback-1", "fallback-2"],
            default_timeout=30.0,
        )
        assert config.primary_model == "custom-model"
        assert config.fallback_models == ["fallback-1", "fallback-2"]
        assert config.default_timeout == 30.0

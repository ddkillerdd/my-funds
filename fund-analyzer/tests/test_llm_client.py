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
        # 纯标量数组对 .get() 调用方无意义 → 返回 None（防止下游 AttributeError）
        assert parse_json_response('[1, 2, 3]') is None

    def test_array_wrapping_object(self):
        # LLM 顶层返回数组包裹对象的行为（portportfolio 场景）→ 取第一个 dict
        data = parse_json_response('[{"overall_health_score": 70, "health_label": "good"}]')
        assert data == {"overall_health_score": 70, "health_label": "good"}

    def test_array_of_mixed(self):
        # 数组内非 dict 元素跳过，取第一个 dict
        data = parse_json_response('[[1,2], {"a": 1}]')
        assert data == {"a": 1}

    def test_array_of_json_strings(self):
        data = parse_json_response('[\"{\\\"a\\\":1}\" ]')
        # 数组内元素可能是 JSON 字符串，也应解析取 dict
        assert data is not None and data.get("a") == 1


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
        # RFC-006: action now carries quantitative decision fields
        assert result["action"]["type"] in (
            "buy", "add", "hold", "watch", "reduce", "sell"
        )
        assert "change_pct" in result["action"]
        assert isinstance(result["action"]["change_pct"], (int, float))
        assert "trigger_conditions" in result["action"]
        assert isinstance(result["action"]["trigger_conditions"], list)
        assert "target_ratio_pct" in result["action"]

    def test_fallback_debate_differentiated(self):
        """RFC-006: bad fund must not get 'hold' — must differentiate."""
        from engine.models import QuantIndicators

        def mk(sharpe, dd, max_dd, vol, macd_sig, trend_dir,
               t_sc, r_sc, v_sc, tech_sc):
            qi = QuantIndicators(
                fund_code="x", fund_name="x", fund_type="",
                current_mv=0, cost=0, mv_ratio=0, pnl_amount=0,
                pnl_pct=0, is_money_fund=False, nav_history_days=250,
            )
            qi.efficiency.sharpe_ratio = sharpe
            qi.risk.current_drawdown_pct = -dd
            qi.risk.max_drawdown_pct = -max_dd
            qi.risk.annual_volatility_pct = vol
            qi.macd.signal = macd_sig
            qi.trend.trend_direction = trend_dir
            views = {
                "overall_trend_score": t_sc,
                "overall_risk_score": r_sc,
                "overall_value_score": v_sc,
                "overall_tech_score": tech_sc,
            }
            return fallback_debate(qi, views, views, views, views)["action"]

        good = mk(1.76, 3.99, 15, 18, "golden_cross_active", "up",
                  78, 40, 85, 80)
        bad = mk(-0.33, 18.1, 40, 42, "death_cross_active", "down",
                 30, 78, 25, 35)
        # Good fund must not be reduced/sold; bad fund must not be held
        assert good["type"] in ("hold", "add"), good
        assert bad["type"] in ("reduce", "sell"), bad
        assert good["change_pct"] >= 0
        assert bad["change_pct"] < 0

    def test_fallback_debate_recovered_trending_hold(self):
        """Sharpe略低但回撤已释放+趋势向上 → 不应误减仓, 应hold (RFC-006b)."""
        from engine.models import QuantIndicators

        qi = QuantIndicators(
            fund_code="x", fund_name="x", fund_type="",
            current_mv=0, cost=0, mv_ratio=0, pnl_amount=0, pnl_pct=0,
            is_money_fund=False, nav_history_days=250,
        )
        # Sharpe=0.2 (<0? 否, >0但<1) / avg~55 / 回撤已释放 / 趋势向上
        # → 旧逻辑: avg<55 or sharpe<0 不中(0.2>0), 但avg可能<55 → 进reduce
        # → 新逻辑: dd_released + trend_up → hold
        qi.efficiency.sharpe_ratio = 0.2
        qi.risk.current_drawdown_pct = -5.0   # 已从深坑回升
        qi.risk.max_drawdown_pct = -30.0      # 历史最大回撤
        qi.risk.annual_volatility_pct = 22.0
        qi.macd.signal = "golden_cross_active"
        qi.trend.trend_direction = "up"
        views = {"overall_trend_score": 58, "overall_risk_score": 55,
                 "overall_value_score": 52, "overall_tech_score": 60}
        act = fallback_debate(qi, views, views, views, views)["action"]
        assert act["type"] == "hold", f"回撤释放+趋势向好不应误减仓: {act}"
        assert act["change_pct"] == 0

    def test_fallback_debate_still_reduce_when_dd_not_released_or_down(self):
        """豁免条件不满足时仍应减仓: 回撤未释放 或 趋势向下."""
        from engine.models import QuantIndicators

        def mk(dd, max_dd, trend):
            qi = QuantIndicators(
                fund_code="x", fund_name="x", fund_type="",
                current_mv=0, cost=0, mv_ratio=0, pnl_amount=0, pnl_pct=0,
                is_money_fund=False, nav_history_days=250,
            )
            qi.efficiency.sharpe_ratio = 0.1
            qi.risk.current_drawdown_pct = -dd
            qi.risk.max_drawdown_pct = -max_dd
            qi.risk.annual_volatility_pct = 25.0
            qi.macd.signal = "neutral"
            qi.trend.trend_direction = trend
            views = {"overall_trend_score": 45, "overall_risk_score": 50,
                     "overall_value_score": 48, "overall_tech_score": 45}
            return fallback_debate(qi, views, views, views, views)["action"]

        # 回撤未释放 (5/8 未过半) + 中性趋势 → 应减仓
        not_released = mk(5.0, 8.0, "sideways")
        assert not_released["type"] in ("reduce", "sell"), not_released
        # 回撤已释放但趋势向下 → 不应豁免, 应减仓/watch
        released_but_down = mk(3.0, 30.0, "down")
        assert released_but_down["type"] in ("reduce", "watch"), released_but_down


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

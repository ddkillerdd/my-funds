"""AdvisorService 模型配置的纯合成失败夹具。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config import Settings
from backend.services import advisor_service
from engine.models import FundHolding, PortfolioInput


class StopAfterCapture(Exception):
    """在捕获模型构造参数后停止，确保测试不会发起模型调用。"""


def _fake_settings(primary="mimo-v2.5-pro", fallbacks=" mimo-v2.5, mimo-v2.5-pro, mimo-v2.5, "):
    """构造不含真实凭据的模型配置。"""
    return SimpleNamespace(
        NEWAPI_BASE_URL="http://127.0.0.1:1/v1",
        NEWAPI_API_KEY="disabled-test-key",
        ANALYZER_PRIMARY_MODEL=primary,
        ANALYZER_FALLBACK_MODELS=fallbacks,
    )


def _fake_portfolio():
    """构造一个非空的虚构持仓输入。"""
    return PortfolioInput(
        holdings=[
            FundHolding(
                fund_code="000001",
                fund_name="合成基金",
                current_mv=100.0,
                cost=100.0,
            )
        ]
    )


def test_analyze_v3_uses_settings_model_chain(monkeypatch):
    """断言 v3 的模型链来自 settings 而不是服务内硬编码。"""
    captured = {}

    class CapturingLLMConfig:
        """只捕获配置参数，不创建网络客户端。"""

        def __init__(self, **kwargs):
            captured.update(kwargs)

    class StopAnalyzer:
        """在配置捕获后停止分析，禁止任何模型调用。"""

        def __init__(self, config, **kwargs):
            raise StopAfterCapture

    monkeypatch.setattr(advisor_service, "LLMConfig", CapturingLLMConfig)
    monkeypatch.setattr(advisor_service, "Analyzer", StopAnalyzer)
    service = advisor_service.AdvisorService.__new__(advisor_service.AdvisorService)
    service.db = object()
    service.settings = _fake_settings()
    service._build_portfolio_input = _fake_portfolio

    with pytest.raises(StopAfterCapture):
        service._analyze_v3()

    assert captured["primary_model"] == "mimo-v2.5-pro"
    assert captured["fallback_models"] == ["mimo-v2.5"]
    assert captured["model_assignments"] == {
        "trend": "mimo-v2.5-pro",
        "risk": "mimo-v2.5-pro",
        "value": "mimo-v2.5-pro",
        "tech": "mimo-v2.5-pro",
        "portfolio": "mimo-v2.5-pro",
        "debate": "mimo-v2.5",
        "cross_val": "mimo-v2.5",
    }


def _service(settings):
    """构造不连接数据库的 AdvisorService 实例。"""
    service = advisor_service.AdvisorService.__new__(advisor_service.AdvisorService)
    service.db = object()
    service.settings = settings
    return service


def test_settings_have_newapi_model_defaults():
    """断言 Settings 的默认主备模型为应用网关模型 ID。"""
    assert Settings.model_fields["ANALYZER_PRIMARY_MODEL"].default == "mimo-v2.5-pro"
    assert Settings.model_fields["ANALYZER_FALLBACK_MODELS"].default == "mimo-v2.5"


def test_fallback_cleanup_preserves_first_independent_model():
    """断言备用链清理空白、重复和主模型后保持首次顺序。"""
    config = _service(
        _fake_settings("primary-model", " , backup-b, primary-model, backup-a, backup-b, ")
    )._build_llm_config()

    assert config.fallback_models == ["backup-b", "backup-a"]
    assert config.model_assignments["debate"] == "backup-b"
    assert config.model_assignments["cross_val"] == "backup-b"
    for role in ("trend", "risk", "value", "tech", "portfolio"):
        assert config.model_assignments[role] == "primary-model"


def test_no_independent_fallback_uses_primary_everywhere():
    """断言没有独立备用模型时回退链和七个角色均安全回到主模型。"""
    config = _service(
        _fake_settings("mimo-v2.5-pro", " , mimo-v2.5-pro, mimo-v2.5-pro, ")
    )._build_llm_config()

    assert config.fallback_models == ["mimo-v2.5-pro"]
    assert set(config.model_assignments.values()) == {"mimo-v2.5-pro"}
    assert len(config.model_assignments) == 7


def test_blank_primary_fails_before_llm_config_or_external_action(monkeypatch):
    """断言空白主模型在构造 LLMConfig 前失败且不泄露密钥。"""
    settings = _fake_settings("   ", "mimo-v2.5")
    settings.NEWAPI_API_KEY = "secret-test-key"
    service = _service(settings)
    monkeypatch.setattr(
        advisor_service,
        "LLMConfig",
        lambda **kwargs: pytest.fail("空白主模型不应构造 LLMConfig"),
    )

    with pytest.raises(ValueError) as error:
        service._build_llm_config()

    assert "secret-test-key" not in str(error.value)


def test_analyze_v3_uses_the_unified_builder(monkeypatch):
    """断言 _analyze_v3 只通过统一方法构造 Analyzer 配置。"""
    sentinel = object()
    captured = {}

    class StopAnalyzer:
        """捕获统一配置后停止，禁止任何模型调用。"""

        def __init__(self, config, **kwargs):
            captured["config"] = config
            raise StopAfterCapture

    service = _service(_fake_settings())
    service._build_portfolio_input = _fake_portfolio
    service._build_llm_config = lambda: sentinel
    monkeypatch.setattr(advisor_service, "Analyzer", StopAnalyzer)

    with pytest.raises(StopAfterCapture):
        service._analyze_v3()

    assert captured["config"] is sentinel


def test_model_argument_remains_compatibility_only():
    """断言历史 model 参数不会绕过统一 v3 配置。"""
    service = _service(_fake_settings())
    calls = []
    service._analyze_v3 = lambda: calls.append("v3") or {"ok": True}

    assert service.analyze(model="caller-selected-model", engine="v3") == {"ok": True}
    assert calls == ["v3"]


def test_protected_old_model_literals_are_absent_from_advisor_service():
    """断言 advisor_service 不再保留四个旧模型字面量。"""
    source = Path(advisor_service.__file__).read_text(encoding="utf-8")
    for old_model in (
        "deepseek-v4-flash",
        "minimax-m3",
        "stepfun-ai/step-3.7-flash",
        "nvidia/nvidia-nemotron-nano-9b-v2",
    ):
        assert source.count(old_model) == 0


def test_analyzer_has_no_retired_hardcoded_fallback_models():
    """断言分析器回退链只使用统一配置，不再引用已退役模型。"""
    analyzer_source = Path(advisor_service.__file__).parents[3] / "fund-analyzer" / "engine" / "analyzer.py"
    source = analyzer_source.read_text(encoding="utf-8")

    for old_model in (
        "nvidia/nvidia-nemotron-nano-9b-v2",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "deepseek-ai/deepseek-v4-flash",
    ):
        assert old_model not in source


def test_configured_fallback_can_return_from_secondary_to_primary():
    """断言备用角色失败时能够回到主模型，不会直接进入纯计算降级。"""
    config = advisor_service.LLMConfig(
        api_base="http://127.0.0.1:1/v1",
        api_key="disabled-test-key",
        primary_model="primary-model",
        fallback_models=["secondary-model"],
    )
    analyzer = advisor_service.Analyzer(config)

    assert analyzer._configured_fallback_model("primary-model") == "secondary-model"
    assert analyzer._configured_fallback_model("secondary-model") == "primary-model"


def test_recommendation_runtime_uses_configured_models_only():
    """断言荐基运行时不再保留退役模型字面量。"""
    backend_root = Path(advisor_service.__file__).parents[1]
    analyzer_root = backend_root.parents[1] / "fund-analyzer" / "engine"
    paths = (
        backend_root / "api" / "advisor.py",
        backend_root / "api" / "recommend.py",
        backend_root / "api" / "scheduler.py",
        backend_root / "scheduler" / "advisor_job.py",
        backend_root / "services" / "plan_recommender.py",
        backend_root / "services" / "recommend_service.py",
        backend_root.parent / "frontend" / "src" / "views" / "SettingsView.vue",
        analyzer_root / "screen_runner.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    for old_model in (
        "nvidia/nvidia-nemotron-nano-9b-v2",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
        "deepseek-ai/deepseek-v4-flash",
        "stepfun-ai/step-3.7-flash",
    ):
        assert old_model not in source


def test_plan_recommender_model_chain_uses_settings_and_deduplicates():
    """断言计划荐基链来自统一配置，并清理主备模型重复项。"""
    from backend.services.plan_recommender import PlanRecommenderService

    settings = _fake_settings(
        "primary-model",
        " backup-b, primary-model, backup-a, backup-b, ",
    )

    assert PlanRecommenderService._configured_model_chain(settings) == [
        "primary-model",
        "backup-b",
        "backup-a",
    ]

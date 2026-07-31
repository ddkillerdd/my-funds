"""
FundAnalyzer — Main Pipeline

5-step sequential analysis:
  Step 0: Quant computation (Python, <1s)
  Step 1: 4-viewpoint analysis per fund (LLM, ~16 calls)
  Step 2: Debate synthesis per fund (LLM, ~4 calls)
  Step 3: Portfolio synthesis (LLM, 1 call)
  Step 4: Cross-validation audit (LLM, 1 call)
  Step 5: Report assembly (Python)

Total: 5N+2 LLM calls for N active funds.
"""

from __future__ import annotations
import json
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from .models import (
    NavPoint,
    FundHolding,
    PortfolioInput,
    AnalysisReport,
    QuantIndicators,
    FundDiagnosis,
    PortfolioDiagnosis,
    GlobalConfidence,
    HistoricalComparison,
    HistoricalChange,
    Completeness,
    Degradation,
    PortfolioGroundTruth,
    CorrelationData,
    ConcentrationData,
    EfficientFrontierData,
    TrendViewDiagnosis,
    RiskViewDiagnosis,
    ValueViewDiagnosis,
    TechnicalViewDiagnosis,
    DebateSummary,
    Contradiction,
    DiagnosisItem,
    RebalanceSuggestion,
)
from .quant import compute_all, build_ground_truth
from .portfolio_quant import correlation_matrix, concentration, efficient_frontier
from .prompts import (
    build_fact_card,
    build_trend_prompt,
    build_risk_prompt,
    build_value_prompt,
    build_technical_prompt,
    build_debate_prompt,
    build_portfolio_prompt,
    build_cross_validation_prompt,
)
from .llm_client import (
    LLMConfig,
    LLMClient,
    parse_json_response,
    validate_diagnosis_json,
    normalize_action,
    fallback_trend_diagnosis,
    fallback_risk_diagnosis,
    fallback_value_diagnosis,
    fallback_technical_diagnosis,
    fallback_debate,
)

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))


class Analyzer:
    """Main analysis engine."""

    def __init__(self, llm_config: LLMConfig):
        self.llm = LLMClient(llm_config)
        self.config = llm_config

    def analyze(self, portfolio: PortfolioInput) -> AnalysisReport:
        """
        Run complete analysis pipeline.

        Args:
            portfolio: PortfolioInput with holdings + nav_history populated.

        Returns:
            AnalysisReport — complete structured report.
        """
        start_time = time.time()
        report = AnalysisReport()

        # ==========================================================
        # Step 0: Quant computation
        # ==========================================================
        quant_start = time.time()
        ground = build_ground_truth(portfolio.holdings)
        per_fund_qi: List[QuantIndicators] = ground.pop("per_fund")

        # Portfolio-level quant
        corr = correlation_matrix(portfolio.holdings)
        conc = concentration(portfolio.holdings)
        ef = efficient_frontier(portfolio.holdings)

        report.data_duration_seconds = round(time.time() - quant_start, 2)

        # RFC-006 方案D / RFC-009 Phase C: 市场基准对比
        # Populate qi.peer_benchmark for each active fund when an index series
        # is available, so the fact card can frame risk/return vs the大盘.
        if portfolio.benchmark_nav_history:
            benchmark_points = [
                (getattr(p, "date", "") or "", float(p.nav))
                for p in portfolio.benchmark_nav_history if p.nav is not None
            ]
            _benchmarked = 0
            for qi in per_fund_qi:
                try:
                    from .market_data import compute_peer_benchmark
                    pb = compute_peer_benchmark(qi, benchmark_points)
                    if pb is not None:
                        _benchmarked += 1
                except Exception as e:
                    logger.debug("peer_benchmark skipped for %s: %s",
                                 qi.fund_code, e)
            if _benchmarked:
                logger.info("peer_benchmark populated for %d funds", _benchmarked)

        # Build portfolio ground truth
        report.ground_truth = PortfolioGroundTruth(
            **ground,
            correlation=corr,
            concentration=conc,
            efficient_frontier=ef,
        )

        # ==========================================================
        # Identify active vs money-fund holdings
        # ==========================================================
        active_funds = [
            (h, qi) for h, qi in zip(portfolio.holdings, per_fund_qi)
            if not h.is_money_fund
        ]
        money_funds = [
            (h, qi) for h, qi in zip(portfolio.holdings, per_fund_qi)
            if h.is_money_fund
        ]

        degraded_steps_all: List[str] = []

        # ==========================================================
        # Step 1-2: Per-fund analysis (4 viewpoints + debate)
        # ==========================================================
        # Money funds get skipped — no LLM analysis needed
        for holding, qi in money_funds:
            fd = FundDiagnosis(
                fund_code=holding.fund_code,
                fund_name=holding.fund_name,
                ground_truth=qi,
                trend_view=TrendViewDiagnosis(
                    overall_score=50,
                    diagnosis=[DiagnosisItem(
                        claim="货币基金，风险极低，无需深度分析",
                        confidence=1.0,
                        evidence="(is_money_fund=True)",
                        sentiment="neutral",
                    )],
                    key_risk="通胀侵蚀购买力",
                    key_opportunity="流动性充裕",
                    confidence=1.0,
                    trend_direction="sideways",
                ),
                risk_view=RiskViewDiagnosis(
                    overall_score=5,
                    risk_level="low",
                    diagnosis=[DiagnosisItem(claim="货币基金，波动率接近零", confidence=1.0, evidence="(is_money_fund=True)", sentiment="positive")],
                    key_risk="",
                    key_opportunity="",
                    confidence=1.0,
                ),
                value_view=ValueViewDiagnosis(
                    overall_score=40,
                    diagnosis=[DiagnosisItem(claim="货币基金收益偏低但零风险", confidence=1.0, evidence="(is_money_fund=True)", sentiment="neutral")],
                    key_risk="",
                    key_opportunity="",
                    confidence=1.0,
                ),
                technical_view=TechnicalViewDiagnosis(
                    overall_score=50,
                    diagnosis=[DiagnosisItem(claim="货币基金无技术面分析价值", confidence=1.0, evidence="(is_money_fund=True)", sentiment="neutral")],
                    key_risk="",
                    key_opportunity="",
                    confidence=1.0,
                ),
                debate_summary=DebateSummary(
                    contradictions=[],
                    consensus_level=1.0,
                    consensus_label="full_consensus",
                    health_score=50,
                    health_label="中性（货币基金）",
                    strengths=["几乎零风险", "流动性好"],
                    risks=["收益率低于通胀"],
                    action=normalize_action({"type": "hold", "confidence": 0.9, "reasoning": "货币基金适合作为流动性储备"}),
                    confidence=1.0,
                ),
            )
            report.per_fund_diagnosis.append(fd)

        # Active funds — full LLM analysis
        for holding, qi in active_funds:
            fd = FundDiagnosis(
                fund_code=holding.fund_code,
                fund_name=holding.fund_name,
                ground_truth=qi,
            )

            # Skip if nav history is too short
            if qi.nav_history_days < 20:
                fd.trend_view = TrendViewDiagnosis(
                    overall_score=40,
                    diagnosis=[DiagnosisItem(
                        claim=f"净值历史仅{qi.nav_history_days}天，不足以进行趋势分析",
                        confidence=0.5,
                        evidence=f"(nav_history_days={qi.nav_history_days})",
                        sentiment="neutral",
                    )],
                    key_risk="数据不足",
                    key_opportunity="",
                    confidence=0.3,
                    uncertainties=["净值历史不足20天"],
                )
                # Fill other views similarly minimal
                fd.risk_view = RiskViewDiagnosis(
                    overall_score=50, risk_level="unknown",
                    diagnosis=[DiagnosisItem(claim="数据不足，无法评估风险", confidence=0.3, evidence="", sentiment="neutral")],
                    confidence=0.3, uncertainties=["净值历史不足20天"],
                )
                fd.value_view = ValueViewDiagnosis(
                    overall_score=50,
                    diagnosis=[DiagnosisItem(claim="数据不足，无法评估价值", confidence=0.3, evidence="", sentiment="neutral")],
                    confidence=0.3, uncertainties=["净值历史不足20天"],
                )
                fd.technical_view = TechnicalViewDiagnosis(
                    overall_score=50,
                    diagnosis=[DiagnosisItem(claim="数据不足，无法进行技术分析", confidence=0.3, evidence="", sentiment="neutral")],
                    confidence=0.3, uncertainties=["净值历史不足20天"],
                )
                fd.debate_summary = DebateSummary(
                    contradictions=[], consensus_level=0.3, consensus_label="partial_disagreement",
                    health_score=40, health_label="无法评估",
                    strengths=[], risks=["数据严重不足"],
                    action=normalize_action({"type": "hold", "confidence": 0.3, "reasoning": "数据不足，建议观望"}),
                    confidence=0.2,
                    uncertainties=["净值历史不足20天"],
                )
                fd.degraded = True
                fd.degraded_steps = ["all_views"]
                degraded_steps_all.append(f"all_views_{holding.fund_code}")
                report.per_fund_diagnosis.append(fd)
                continue

            # === 4 Viewpoint Analysis ===
            views = self._analyze_4_views(qi)
            fd.trend_view = views.get("trend")
            fd.risk_view = views.get("risk")
            fd.value_view = views.get("value")
            fd.technical_view = views.get("technical")
            model_sources = views.get("_model_sources", {})

            # Track degradation
            for vname in ["trend", "risk", "value", "technical"]:
                v = views.get(vname)
                if v and v.uncertainties and any("LLM调用失败" in u for u in v.uncertainties):
                    fd.degraded = True
                    fd.degraded_steps.append(f"{vname}_{holding.fund_code}")
                    degraded_steps_all.append(f"{vname}_{holding.fund_code}")

            # === Debate (with model sources for cross-model comparison) ===
            if fd.trend_view and fd.risk_view and fd.value_view and fd.technical_view:
                fd.debate_summary = self._debate_synthesis(
                    qi,
                    fd.trend_view,
                    fd.risk_view,
                    fd.value_view,
                    fd.technical_view,
                    model_sources=model_sources,
                )
            else:
                # All views failed → pure calculation fallback
                data = fallback_debate(qi, {}, {}, {}, {})
                fd.debate_summary = DebateSummary(
                    health_score=50, health_label="无法评估", confidence=0.3,
                    model_sources=model_sources, model_reliability={}, conflict_models=[],
                )
                fd.degraded = True

            if fd.debate_summary and fd.debate_summary.uncertainties and any("LLM调用失败" in u for u in fd.debate_summary.uncertainties):
                fd.degraded = True
                fd.degraded_steps.append(f"debate_{holding.fund_code}")
                degraded_steps_all.append(f"debate_{holding.fund_code}")

            report.per_fund_diagnosis.append(fd)

        # ==========================================================
        # Step 3: Portfolio synthesis
        # ==========================================================
        report.portfolio_diagnosis = self._portfolio_synthesis(
            portfolio, per_fund_qi, report.per_fund_diagnosis, report.ground_truth
        )

        # ==========================================================
        # Step 4: Cross-validation (skip if all degraded)
        # ==========================================================
        if len(degraded_steps_all) < self.llm.call_count * 0.5:
            # Worth doing cross-validation
            cf = self._cross_validate(report, per_fund_qi, portfolio.holdings)
            if cf:
                report.confidence = cf
        else:
            report.confidence = GlobalConfidence(
                overall=0.3,
                overall_label="低可信度",
                breakdown={"data_quality": 0.8, "analysis_consistency": 0.3, "model_capability": 0.3},
                warnings=["大量LLM调用失败，使用降级分析"],
                suggestion="建议稍后重试或以量化指标为主要参考",
            )

        # ==========================================================
        # Step 5: Assemble meta fields
        # ==========================================================
        report.generated_at = datetime.now(CST).isoformat()
        report.analysis_duration_seconds = round(time.time() - start_time, 1)
        report.model = self.config.primary_model
        report.model_chain = self.llm.models_used
        report.model_roles = self.llm.config.model_assignments
        report.llm_call_count = self.llm.call_count
        report.llm_failure_count = self.llm.failure_count
        report.llm_fallback_count = self.llm.fallback_count

        # Completeness
        total_expected = len(active_funds) * 10  # ~10 indicator categories per fund
        total_computed = sum(
            1 for fd in report.per_fund_diagnosis
            for attr in dir(fd.ground_truth.trend)
            if not attr.startswith("_")
        )
        report.completeness = Completeness(
            total_indicators_computed=total_computed,
            total_indicators_expected=total_computed,  # approximate
            completeness_pct=100.0 - (len(per_fund_qi[0].all_notes) * 3) if per_fund_qi else 100.0,
            data_quality_label=report.ground_truth.overall_data_quality,
        )

        if total_computed > 0:
            report.completeness.completeness_pct = min(100, round(total_computed / total_computed * 100, 1))

        # Degradation
        impact = "none"
        if len(degraded_steps_all) > 0:
            ratio = len(degraded_steps_all) / max(1, len(active_funds) * 5)
            impact = "severe" if ratio > 0.5 else "moderate" if ratio > 0.25 else "minor"
        report.degradation = Degradation(
            any_degraded=len(degraded_steps_all) > 0,
            degraded_steps=list(set(degraded_steps_all)),
            impact=impact,
        )

        # Historical comparison (if previous reports exist)
        if portfolio.previous_report_id:
            report.historical_comparison = self._build_historical_comparison(
                portfolio, report
            )

        return report

    # ==========================================================
    #  PRIVATE METHODS
    # ==========================================================

    def _analyze_4_views(self, qi: QuantIndicators) -> Dict[str, Any]:
        """Run 4 independent viewpoint analyses — each possibly with a different model.

        Model assignment (RFC-005):
          trend  → omni-30b (2.5x depth, covers short+long)
          risk   → omni-30b (specific numerical risk data)
          value  → ds-flash (strongest reasoning for Sharpe/Sortino/Calmar)
          tech   → nano-9b  (MACD/RSI/BB pattern recognition, 9B enough)

        Fallback per viewpoint: primary fail → secondary model → pure calc
        """
        results = {}
        # Track which model was actually used for each view
        model_sources: Dict[str, str] = {}

        # --- Trend View: omni-30b → nano-9b → calc ---
        trend_model = self.llm.config.model_assignments.get("trend", self.llm.config.primary_model)
        trend_fallback = "nvidia/nvidia-nemotron-nano-9b-v2"
        try:
            prompt = build_trend_prompt(qi)
            try:
                raw = self.llm.call(prompt, temperature=0.3, max_tokens=4096,
                                     step_label=f"trend_{qi.fund_code}", model=trend_model)
                model_sources["trend"] = trend_model
            except Exception:
                logger.info(f"Trend model {trend_model} failed, falling back to {trend_fallback}")
                raw = self.llm.call(prompt, temperature=0.3, max_tokens=4096,
                                     step_label=f"trend_{qi.fund_code}_fb", model=trend_fallback)
                model_sources["trend"] = trend_fallback
            data = parse_json_response(raw)
            if data:
                results["trend"] = TrendViewDiagnosis(
                    overall_score=data.get("overall_trend_score"),
                    trend_direction=data.get("trend_direction", "unknown"),
                    trend_strength_label=data.get("trend_strength_label", ""),
                    diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                    key_risk=data.get("key_risk", ""),
                    key_opportunity=data.get("key_opportunity", ""),
                    confidence=data.get("confidence", 0.5),
                    uncertainties=data.get("uncertainties", []),
                )
            else:
                raise ValueError("Failed to parse JSON")
        except Exception as e:
            logger.warning(f"Trend view failed for {qi.fund_code}: {e}")
            model_sources["trend"] = "fallback_calc"
            data = fallback_trend_diagnosis(qi)
            results["trend"] = TrendViewDiagnosis(
                overall_score=data.get("overall_trend_score", 50),
                trend_direction=data.get("trend_direction", "unknown"),
                trend_strength_label=data.get("trend_strength_label", ""),
                diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                key_risk=data.get("key_risk", ""),
                key_opportunity=data.get("key_opportunity", ""),
                confidence=data.get("confidence", 0.4),
                uncertainties=data.get("uncertainties", []),
            )

        # --- Risk View: omni-30b → nano-9b → calc ---
        risk_model = self.llm.config.model_assignments.get("risk", self.llm.config.primary_model)
        try:
            prompt = build_risk_prompt(qi)
            try:
                raw = self.llm.call(prompt, temperature=0.3, max_tokens=4096,
                                     step_label=f"risk_{qi.fund_code}", model=risk_model)
                model_sources["risk"] = risk_model
            except Exception:
                raw = self.llm.call(prompt, temperature=0.3, max_tokens=4096,
                                     step_label=f"risk_{qi.fund_code}_fb", model=trend_fallback)
                model_sources["risk"] = trend_fallback
            data = parse_json_response(raw)
            if data:
                results["risk"] = RiskViewDiagnosis(
                    overall_score=data.get("overall_risk_score"),
                    risk_level=data.get("risk_level", "unknown"),
                    diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                    key_risk=data.get("key_risk", ""),
                    key_opportunity=data.get("key_opportunity", ""),
                    confidence=data.get("confidence", 0.5),
                    uncertainties=data.get("uncertainties", []),
                )
            else:
                raise ValueError("Failed to parse JSON")
        except Exception as e:
            logger.warning(f"Risk view failed for {qi.fund_code}: {e}")
            model_sources["risk"] = "fallback_calc"
            data = fallback_risk_diagnosis(qi)
            results["risk"] = RiskViewDiagnosis(
                overall_score=data.get("overall_risk_score", 50),
                risk_level=data.get("risk_level", "unknown"),
                diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                key_risk=data.get("key_risk", ""),
                key_opportunity=data.get("key_opportunity", ""),
                confidence=data.get("confidence", 0.4),
                uncertainties=data.get("uncertainties", []),
            )

        # --- Value View: ds-flash → omni-30b → calc ---
        value_model = self.llm.config.model_assignments.get("value", self.llm.config.primary_model)
        value_fallback = self.llm.config.model_assignments.get("risk", "nvidia/nvidia-nemotron-nano-9b-v2")
        try:
            prompt = build_value_prompt(qi)
            try:
                raw = self.llm.call(prompt, temperature=0.2, max_tokens=4096,
                                     step_label=f"value_{qi.fund_code}", model=value_model)
                model_sources["value"] = value_model
            except Exception:
                logger.info(f"Value {value_model} failed, falling back to {value_fallback}")
                raw = self.llm.call(prompt, temperature=0.2, max_tokens=4096,
                                     step_label=f"value_{qi.fund_code}_fb", model=value_fallback)
                model_sources["value"] = value_fallback
            data = parse_json_response(raw)
            if data:
                results["value"] = ValueViewDiagnosis(
                    overall_score=data.get("overall_value_score"),
                    diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                    key_risk=data.get("key_risk", ""),
                    key_opportunity=data.get("key_opportunity", ""),
                    confidence=data.get("confidence", 0.5),
                    uncertainties=data.get("uncertainties", []),
                )
            else:
                raise ValueError("Failed to parse JSON")
        except Exception as e:
            logger.warning(f"Value view failed for {qi.fund_code}: {e}")
            model_sources["value"] = "fallback_calc"
            data = fallback_value_diagnosis(qi)
            results["value"] = ValueViewDiagnosis(
                overall_score=data.get("overall_value_score", 50),
                diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                key_risk=data.get("key_risk", ""),
                key_opportunity=data.get("key_opportunity", ""),
                confidence=data.get("confidence", 0.4),
                uncertainties=data.get("uncertainties", []),
            )

        # --- Technical View: nano-9b → omni-30b → calc ---
        tech_model = self.llm.config.model_assignments.get("tech", "nvidia/nvidia-nemotron-nano-9b-v2")
        tech_fallback = self.llm.config.model_assignments.get("trend", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
        try:
            prompt = build_technical_prompt(qi)
            try:
                raw = self.llm.call(prompt, temperature=0.3, max_tokens=4096,
                                     step_label=f"tech_{qi.fund_code}", model=tech_model)
                model_sources["tech"] = tech_model
            except Exception:
                raw = self.llm.call(prompt, temperature=0.3, max_tokens=4096,
                                     step_label=f"tech_{qi.fund_code}_fb", model=tech_fallback)
                model_sources["tech"] = tech_fallback
            data = parse_json_response(raw)
            if data:
                results["technical"] = TechnicalViewDiagnosis(
                    overall_score=data.get("overall_tech_score"),
                    diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                    key_risk=data.get("key_risk", ""),
                    key_opportunity=data.get("key_opportunity", ""),
                    confidence=data.get("confidence", 0.5),
                    uncertainties=data.get("uncertainties", []),
                )
            else:
                raise ValueError("Failed to parse JSON")
        except Exception as e:
            logger.warning(f"Technical view failed for {qi.fund_code}: {e}")
            model_sources["tech"] = "fallback_calc"
            data = fallback_technical_diagnosis(qi)
            results["technical"] = TechnicalViewDiagnosis(
                overall_score=data.get("overall_tech_score", 50),
                diagnosis=[DiagnosisItem(**d) for d in data.get("diagnosis", []) if isinstance(d, dict)],
                key_risk=data.get("key_risk", ""),
                key_opportunity=data.get("key_opportunity", ""),
                confidence=data.get("confidence", 0.4),
                uncertainties=data.get("uncertainties", []),
            )

        # Stash model sources for later use
        results["_model_sources"] = model_sources
        return results

    def _debate_synthesis(
        self,
        qi: QuantIndicators,
        trend: TrendViewDiagnosis,
        risk: RiskViewDiagnosis,
        value: ValueViewDiagnosis,
        technical: TechnicalViewDiagnosis,
        model_sources: Optional[Dict[str, str]] = None,
    ) -> DebateSummary:
        """Run debate synthesis with model-source-aware prompt.

        RFC-005: debates use ds-flash (strongest reasoning), with omni-30b fallback.
        Two-layer check: signal-level contradictions + model-level reliability.
        """
        debate_model = self.llm.config.model_assignments.get("debate", "deepseek-ai/deepseek-v4-flash")
        debate_fallback = self.llm.config.model_assignments.get("risk", "nvidia/nvidia-nemotron-nano-9b-v2")
        model_sources = model_sources or {}

        try:
            # Build model-source-enriched prompt
            source_info = "\n".join(f"- {k} viewpoint: {v}" for k, v in model_sources.items())
            prompt = build_debate_prompt(
                qi,
                trend=json.dumps(trend.__dict__, default=str, ensure_ascii=False, indent=2),
                risk=json.dumps(risk.__dict__, default=str, ensure_ascii=False, indent=2),
                value=json.dumps(value.__dict__, default=str, ensure_ascii=False, indent=2),
                technical=json.dumps(technical.__dict__, default=str, ensure_ascii=False, indent=2),
            )
            # Inject model source context into debate prompt
            prompt += f"\n\n## 模型来源（不同视角由不同AI模型分析）\n{source_info}\n\n请检查：不同模型的判断是否存在系统性偏差？（例如某个模型在回撤极大的基金上仍然给高分）"

            try:
                raw = self.llm.call(prompt, temperature=0.1, max_tokens=4096,
                                     step_label=f"debate_{qi.fund_code}", model=debate_model)
                debate_model_used = debate_model
            except Exception:
                logger.info(f"Debate model {debate_model} failed, falling back to {debate_fallback}")
                raw = self.llm.call(prompt, temperature=0.1, max_tokens=4096,
                                     step_label=f"debate_{qi.fund_code}_fb", model=debate_fallback)
                debate_model_used = debate_fallback

            data = parse_json_response(raw)

            if data:
                raw_action = data.get("action") or {}
                return DebateSummary(
                    contradictions=[
                        Contradiction(**c) for c in data.get("contradictions", [])
                        if isinstance(c, dict) and "views" in c
                    ],
                    consensus_level=data.get("consensus_level", 0.5),
                    consensus_label=data.get("consensus_label", "unknown"),
                    health_score=data.get("health_score", 50),
                    health_label=data.get("health_label", ""),
                    strengths=data.get("strengths", []),
                    risks=data.get("risks", []),
                    action=normalize_action(raw_action),
                    confidence=data.get("confidence", 0.5),
                    uncertainties=data.get("uncertainties", []),
                    # v5: model-level reliability
                    model_sources=model_sources,
                    model_reliability=data.get("model_reliability",
                        {v: 0.7 if "fallback" not in v else 0.4 for v in set(model_sources.values())}),
                    conflict_models=data.get("conflict_models", []),
                )
            else:
                raise ValueError("Failed to parse JSON")
        except Exception as e:
            logger.warning(f"Debate failed for {qi.fund_code}: {e}")
            data = fallback_debate(qi, trend.__dict__, risk.__dict__, value.__dict__, technical.__dict__)
            return DebateSummary(
                contradictions=[Contradiction(**c) for c in data.get("contradictions", []) if isinstance(c, dict)],
                consensus_level=data.get("consensus_level", 0.5),
                consensus_label=data.get("consensus_label", "unknown"),
                health_score=data.get("health_score", 50),
                health_label=data.get("health_label", ""),
                strengths=data.get("strengths", []),
                risks=data.get("risks", []),
                action=normalize_action(data.get("action") or {}),
                confidence=data.get("confidence", 0.4),
                uncertainties=data.get("uncertainties", []),
                model_sources=model_sources,
                model_reliability={v: 0.4 for v in set(model_sources.values())},
                conflict_models=[],
            )

    def _portfolio_synthesis(
        self,
        portfolio: PortfolioInput,
        per_fund_qi: List[QuantIndicators],
        fund_diagnoses: List[FundDiagnosis],
        ground: PortfolioGroundTruth,
    ) -> PortfolioDiagnosis:
        """Synthesize portfolio-level diagnosis."""
        # Build portfolio data string
        lines = []
        lines.append(f"=== 组合概况 ===")
        lines.append(f"总市值: {ground.total_market_value:.2f}元")
        lines.append(f"总成本: {ground.total_cost:.2f}元")
        lines.append(f"总盈亏: {ground.total_pnl:.2f}元 ({ground.total_pnl_pct:.2f}%)")
        lines.append(f"持仓数量: {ground.holding_count} (活跃: {ground.active_count}, 货币: {ground.money_fund_count})")
        lines.append(f"数据天数: {ground.data_days}")
        lines.append(f"数据质量: {ground.overall_data_quality}")
        lines.append("")

        if ground.correlation:
            lines.append(f"=== 相关性矩阵 ===")
            lines.append(f"基金: {ground.correlation.labels}")
            for i, row in enumerate(ground.correlation.matrix):
                lines.append(f"  {ground.correlation.labels[i]}: {[round(r, 4) if r else 'N/A' for r in row]}")
            lines.append(f"平均成对相关性: {ground.correlation.avg_pairwise_corr}")
            if ground.correlation.high_corr_pairs:
                for p in ground.correlation.high_corr_pairs:
                    lines.append(f"⚠ 高相关性: {p['pair']} = {p['correlation']}")
            lines.append("")

        if ground.concentration:
            lines.append(f"=== 集中度 ===")
            lines.append(f"HHI: {ground.concentration.hhi_index} ({ground.concentration.hhi_label})")
            lines.append(f"Top1: {ground.concentration.top1_pct}%  Top3: {ground.concentration.top3_pct}%")
            lines.append("")

        if ground.efficient_frontier:
            lines.append(f"=== 有效前沿 ===")
            lines.append(f"模拟次数: {ground.efficient_frontier.simulations}")
            lines.append(f"最优Sharpe权重: {ground.efficient_frontier.optimal_sharpe_weights}")
            lines.append(f"最小波动权重: {ground.efficient_frontier.min_vol_weights}")
            lines.append(f"当前位置: 风险={ground.efficient_frontier.current_position_risk}% 收益={ground.efficient_frontier.current_position_return}%")
            lines.append(f"距有效前沿: {ground.efficient_frontier.distance_to_frontier_pct}% ({ground.efficient_frontier.position_quality})")
            lines.append("")

        portfolio_data = "\n".join(lines)

        # Build fund summaries
        summaries = []
        for fd in fund_diagnoses:
            if fd.debate_summary:
                s = f"### {fd.fund_name} ({fd.fund_code})\n"
                s += f"健康评分: {fd.debate_summary.health_score}/100 ({fd.debate_summary.health_label})\n"
                s += f"行动建议: {fd.debate_summary.action.get('type', 'hold')}\n"
                s += f"优势: {', '.join(fd.debate_summary.strengths[:3])}\n"
                s += f"风险: {', '.join(fd.debate_summary.risks[:3])}\n"
                summaries.append(s)

        fund_summaries = "\n\n".join(summaries)

        try:
            prompt = build_portfolio_prompt(portfolio_data, fund_summaries)
            # Portfolio synthesis uses omni-30b (comprehensive) with nano fallback
            portfolio_model = self.llm.config.model_assignments.get("portfolio",
                "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
            portfolio_fallback = "nvidia/nvidia-nemotron-nano-9b-v2"
            try:
                raw = self.llm.call(prompt, temperature=0.1, max_tokens=4096,
                                     step_label="portfolio", model=portfolio_model)
            except Exception:
                raw = self.llm.call(prompt, temperature=0.1, max_tokens=4096,
                                     step_label="portfolio_fb", model=portfolio_fallback)
            data = parse_json_response(raw)

            if data:
                return PortfolioDiagnosis(
                    overall_health_score=data.get("overall_health_score", 50),
                    health_label=data.get("health_label", ""),
                    concentration_risk=data.get("concentration_risk", {}),
                    correlation_issues=data.get("correlation_issues", []),
                    efficient_frontier_analysis=data.get("efficient_frontier_analysis", {}),
                    rebalance_suggestions=[
                        RebalanceSuggestion(**r) for r in data.get("rebalance_suggestions", [])
                        if isinstance(r, dict)
                    ],
                    strengths=data.get("strengths", []),
                    weaknesses=data.get("weaknesses", []),
                    confidence=data.get("confidence", 0.5),
                )
            else:
                raise ValueError("Failed to parse JSON")
        except Exception as e:
            logger.warning(f"Portfolio synthesis failed: {e}")
            return PortfolioDiagnosis(
                overall_health_score=50,
                health_label="无法评估",
                concentration_risk={},
                correlation_issues=[],
                efficient_frontier_analysis={},
                rebalance_suggestions=[],
                strengths=[],
                weaknesses=[],
                confidence=0.3,
                notes=["LLM调用失败，使用降级分析"],
            )

    def _cross_validate(
        self,
        report: AnalysisReport,
        per_fund_qi: List[QuantIndicators],
        holdings: List[FundHolding],
    ) -> GlobalConfidence:
        """Cross-validate the full report for contradictions and hallucinations."""
        # Build full report text
        report_text = json.dumps(report.__dict__, default=str, ensure_ascii=False, indent=2)
        # Truncate if too long
        if len(report_text) > 8000:
            report_text = report_text[:8000] + "\n... (truncated)"

        # Build all fact cards
        fact_cards = []
        for qi in per_fund_qi:
            fact_cards.append(build_fact_card(qi))
        all_facts = "\n\n---\n\n".join(fact_cards)

        try:
            prompt = build_cross_validation_prompt(report_text, all_facts)
            # Cross-validation uses nano-9b (checklist-like, no deep reasoning needed)
            crossval_model = self.llm.config.model_assignments.get("cross_val", "nvidia/nvidia-nemotron-nano-9b-v2")
            raw = self.llm.call(prompt, temperature=0.0, max_tokens=4096,
                                 step_label="cross_val", model=crossval_model)
            data = parse_json_response(raw)

            if data:
                return GlobalConfidence(
                    overall=data.get("adjusted_overall_confidence", 0.5),
                    overall_label=(
                        "高可信度" if data.get("adjusted_overall_confidence", 0) > 0.75
                        else "中等可信" if data.get("adjusted_overall_confidence", 0) > 0.5
                        else "低可信度" if data.get("adjusted_overall_confidence", 0) > 0.3
                        else "极低可信度"
                    ),
                    breakdown={
                        "data_quality": 0.8,
                        "analysis_consistency": data.get("adjusted_overall_confidence", 0.5),
                        "model_capability": 0.65,
                    },
                    warnings=data.get("warnings", []),
                    suggestion="",
                )
            else:
                raise ValueError("Failed to parse JSON")
        except Exception as e:
            logger.warning(f"Cross-validation failed: {e}")
            return GlobalConfidence(
                overall=0.45,
                overall_label="中等可信",
                breakdown={"data_quality": 0.8, "analysis_consistency": 0.45, "model_capability": 0.6},
                warnings=["交叉验证LLM调用失败"],
                suggestion="",
            )

    def _build_historical_comparison(
        self,
        portfolio: PortfolioInput,
        report: AnalysisReport,
    ) -> HistoricalComparison:
        """Compare current analysis with previous report(s)."""
        hc = HistoricalComparison()
        previous_reports = portfolio.previous_reports_json or []
        if not previous_reports:
            return hc

        prev = previous_reports[-1] if previous_reports else None
        if not prev:
            return hc

        hc.previous_report_id = prev.get("id")
        hc.previous_generated_at = prev.get("created_at")

        # Compare health scores
        prev_diagnoses = prev.get("report_json", {}).get("per_fund_diagnosis", [])
        for fd in report.per_fund_diagnosis:
            prev_fd = None
            for pfd in prev_diagnoses:
                if pfd.get("fund_code") == fd.fund_code:
                    prev_fd = pfd
                    break

            if prev_fd and fd.debate_summary:
                prev_health = prev_fd.get("debate_summary", {}).get("health_score")
                curr_health = fd.debate_summary.health_score
                if prev_health is not None and curr_health is not None:
                    delta = curr_health - prev_health
                    hc.changes.append(HistoricalChange(
                        fund_code=fd.fund_code,
                        dimension="health_score",
                        previous_value=prev_health,
                        current_value=curr_health,
                        delta=f"{'+' if delta >= 0 else ''}{delta}",
                        interpretation=(
                            "健康度改善" if delta > 3 else
                            "健康度下降" if delta < -3 else
                            "健康度基本持平"
                        ),
                    ))

        return hc


# ============================================================
#  TOP-LEVEL SHORTHAND
# ============================================================

def analyze(
    holdings: List[FundHolding],
    api_base: str,
    api_key: str,
    primary_model: str = "nvidia/nvidia-nemotron-nano-9b-v2",
    previous_report_id: Optional[int] = None,
    previous_reports_json: Optional[List[dict]] = None,
    benchmark_history: Optional[List[NavPoint]] = None,
) -> AnalysisReport:
    """
    Convenience function: analyze with minimal boilerplate.

    Args:
        holdings: List of FundHolding with nav_history populated
        api_base: OpenAI-compatible API base URL (e.g. http://127.0.0.1:8443/v1)
        api_key: API key
        primary_model: Model name
        previous_report_id: ID of previous report for comparison
        previous_reports_json: Previous report JSONs for historical comparison
        benchmark_history: Optional benchmark nav history

    Returns:
        AnalysisReport
    """
    config = LLMConfig(api_base=api_base, api_key=api_key, primary_model=primary_model)
    analyzer = Analyzer(config)
    portfolio = PortfolioInput(
        holdings=holdings,
        benchmark_nav_history=benchmark_history,
        previous_report_id=previous_report_id,
        previous_reports_json=previous_reports_json or [],
    )
    return analyzer.analyze(portfolio)

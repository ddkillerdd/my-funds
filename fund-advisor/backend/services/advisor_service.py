"""AI Advisor Service — v3 集成 FundAnalyzer 引擎

架构: 委托给 fund-analyzer (独立包), 本文件仅做数据适配 + API 桥接

数据流:
  DB (FundHolding + FundNavHistory) → PortfolioInput → FundAnalyzer → AnalysisReport → API JSON

保留 v2 兼容:
  analyze(engine="v2") 使用旧引擎
  analyze(engine="v3") 使用 FundAnalyzer (默认)
"""

import json
import logging
import re
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.config import get_settings
from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.nav_history import FundNavHistory

# 确保可以 import fund_analyzer
sys.path.insert(0, "/root/.openclaw/workspace/fund-analyzer")

from engine.models import (
    NavPoint, FundHolding as FAHolding, PortfolioInput, AnalysisReport,
    QuantIndicators, FundDiagnosis, PortfolioDiagnosis, GlobalConfidence,
    DebateSummary, TrendViewDiagnosis, RiskViewDiagnosis,
    ValueViewDiagnosis, TechnicalViewDiagnosis, DiagnosisItem,
    PortfolioGroundTruth, Completeness, Degradation,
)
from engine.analyzer import Analyzer
from engine.llm_client import LLMConfig

logger = logging.getLogger(__name__)


class AdvisorService:
    """AI 投资顾问 (v3 FundAnalyzer 集成版)"""

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    # ═══════════════════════════════════════════════════
    # 公有 API
    # ═══════════════════════════════════════════════════

    def analyze(self, model: str = None, engine: str = "v3") -> dict:
        """运行投资组合分析。

        Args:
            model: 保留兼容 (v3 使用固定模型链, 忽略此参数)
            engine: "v3" (默认, FundAnalyzer) 或 "v2" (旧引擎)

        Returns:
            dict: 分析报告 (v3 格式或 v2 格式)
        """
        if engine == "v2":
            return self._analyze_v2()

        return self._analyze_v3()

    def _analyze_v3(self) -> dict:
        """v3: 使用 FundAnalyzer 引擎"""
        t0 = time.time()

        # 1. 从 DB 加载数据 → PortfolioInput
        portfolio_input = self._build_portfolio_input()
        if not portfolio_input.holdings:
            return {"error": "no_holdings", "message": "没有持仓数据"}

        # 2. 创建 Analyzer 并执行（RFC-005 多模型分发策略）
        config = LLMConfig(
            api_base=self.settings.NEWAPI_BASE_URL,
            api_key=self.settings.NEWAPI_API_KEY,
            primary_model="nvidia/nvidia-nemotron-nano-9b-v2",
            fallback_models=["deepseek-ai/deepseek-v4-flash"],
            default_timeout=60.0,
            fallback_timeout=90.0,
            model_assignments={
                "trend": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                "risk": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                "value": "deepseek-ai/deepseek-v4-flash",
                "tech": "nvidia/nvidia-nemotron-nano-9b-v2",
                "debate": "deepseek-ai/deepseek-v4-flash",
                "portfolio": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                "cross_val": "nvidia/nvidia-nemotron-nano-9b-v2",
            },
        )
        analyzer = Analyzer(config)
        report = analyzer.analyze(portfolio_input)

        # 3. 转换为 API JSON
        result = self._report_to_api_json(report, t0)
        return result

    def _analyze_v2(self) -> dict:
        """v2: 使用旧的分析引擎 (逐基金 prompt + 合成 + 反方)"""
        from backend.services.facts_computer import compute_portfolio_facts
        facts = compute_portfolio_facts(self.db)

        # 简化版 v2 — 复用旧逻辑
        fund_analyses = self._step1_per_fund_analysis_v2(facts)
        synthesis = self._step2_synthesis_v2(facts, fund_analyses)
        debate = {"passed": True, "severity": "none", "issues": []}

        return self._step4_assemble_v2(facts, fund_analyses, synthesis, debate, time.time())

    # ═══════════════════════════════════════════════════
    # 数据适配: DB → FundAnalyzer PortfolioInput
    # ═══════════════════════════════════════════════════

    def _build_portfolio_input(self) -> PortfolioInput:
        """从 DB 读取持仓 + 净值历史，构建 PortfolioInput"""
        holdings = self._load_holdings_from_db()
        if not holdings:
            return PortfolioInput(holdings=[])

        fa_holdings = []

        for h, f in holdings:
            code = h.fund_code
            name = h.fund_name
            ftype = f.fund_type if f else "未知"
            shares = float(h.shares or 0)

            # 当前市值
            if f and f.latest_nav and shares:
                current_mv = shares * float(f.latest_nav)
            elif h.market_value:
                current_mv = float(h.market_value)
            else:
                current_mv = 0.0

            # 成本
            if h.cost_nav and shares:
                cost = shares * float(h.cost_nav)
            else:
                cost = 0.0

            # 总市值占比
            mv_ratio = 0.0  # 稍后计算

            # 判断货币基金
            is_money = code in self._money_fund_codes()

            # 加载净值历史
            nav_history = self._load_nav_history(code)

            fa_h = FAHolding(
                fund_code=code,
                fund_name=name,
                fund_type=ftype,
                current_mv=round(current_mv, 2),
                cost=round(cost, 2),
                mv_ratio=mv_ratio,
                is_money_fund=is_money,
                nav_history=nav_history,
            )
            fa_holdings.append(fa_h)

        # 计算占比
        total_mv = sum(h.current_mv for h in fa_holdings)
        if total_mv > 0:
            for h in fa_holdings:
                h.mv_ratio = round(h.current_mv / total_mv * 100, 1)

        return PortfolioInput(holdings=fa_holdings)

    def _load_holdings_from_db(self):
        """加载活跃持仓 (status=1) + 关联基金信息"""
        rows = self.db.execute(
            select(FundHolding, Fund)
            .outerjoin(Fund, FundHolding.fund_code == Fund.fund_code)
            .where(FundHolding.status == 1)
        ).all()
        return rows

    def _money_fund_codes(self) -> set:
        rows = self.db.execute(
            select(Fund.fund_code).where(Fund.fund_type == "货币型")
        ).scalars().all()
        return set(rows)

    def _load_nav_history(self, fund_code: str, limit: int = 252) -> List[NavPoint]:
        """加载单只基金的净值历史 (最多1年)"""
        rows = self.db.execute(
            select(FundNavHistory.nav_date, FundNavHistory.unit_nav)
            .where(FundNavHistory.fund_code == fund_code)
            .order_by(FundNavHistory.nav_date.asc())
            .limit(limit)
        ).all()

        return [
            NavPoint(
                date=str(r.nav_date) if r.nav_date else "",
                nav=float(r.unit_nav),
            )
            for r in rows
        ]

    # ═══════════════════════════════════════════════════
    # 报告格式转换: AnalysisReport → API JSON
    # ═══════════════════════════════════════════════════

    def _report_to_api_json(self, report: AnalysisReport, t0: float) -> dict:
        """将 AnalysisReport 转换为 API 兼容的 JSON 格式"""

        gt = report.ground_truth

        # ---- 市场分析 ----
        # 提取所有基金的共识趋势方向
        directions = []
        for fd in report.per_fund_diagnosis:
            if fd.trend_view and fd.trend_view.trend_direction != "unknown":
                directions.append(fd.trend_view.trend_direction)
        up_count = directions.count("up") if directions else 0
        down_count = directions.count("down") if directions else 0
        if up_count > down_count:
            market_trend = f"上涨 (看多 {up_count}/{len(directions)})"
        elif down_count > up_count:
            market_trend = f"下跌 (看空 {down_count}/{len(directions)})"
        else:
            market_trend = "震荡/分歧"

        # 从组合诊断提取信号
        key_signals = []
        if report.portfolio_diagnosis:
            pd = report.portfolio_diagnosis
            if pd.concentration_risk:
                key_signals.append(f"集中度: {pd.concentration_risk.get('level', 'unknown')} ({pd.concentration_risk.get('detail', '')[:50]})")
            key_signals.extend(pd.strengths[:2])
            key_signals.extend(pd.weaknesses[:2])

        market_analysis = {
            "trend": market_trend,
            "key_signals": key_signals or ["分析完成"],
            "overall": report.portfolio_diagnosis.health_label if report.portfolio_diagnosis else "分析完成",
            "computed_signals": [],
        }

        # ---- 持仓健康度 ----
        holdings_health = []
        for fd in report.per_fund_diagnosis:
            ds = fd.debate_summary
            # 清洗 risks：去掉括号里的证据引用
            clean_risks = []
            if ds:
                for r in ds.risks[:3]:
                    # 去掉括号内证据引用：含等号或纯数字百分比
                    cleaned = re.sub(r'[（(][^）)]*(?:[=≈]|[-+]?\d)[^）)]*[）)]', '', r)
                    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
                    if cleaned:
                        clean_risks.append(cleaned)
            holdings_health.append({
                "fund_code": fd.fund_code,
                "fund_name": fd.fund_name,
                "health_score": ds.health_score if ds else 50,
                "health_diagnosis": ds.health_label if ds else "",
                "concerns": "; ".join(clean_risks) if ds else "",
                "suggestion": ds.action.get("type", "hold") if ds and ds.action else "hold",
                "data_citations": [],
                # v3 新增字段
                "v3_consensus": ds.consensus_label if ds else "",
                "v3_contradictions": len(ds.contradictions) if ds else 0,
                "v3_strengths": ds.strengths[:3] if ds else [],
                "v3_risks": clean_risks if ds else [],
            })

        # ---- 操作建议 ----
        actions = []
        if report.portfolio_diagnosis:
            pd = report.portfolio_diagnosis
            for rs in pd.rebalance_suggestions:
                # 从持仓中找到基金名
                fund_name = rs.fund_code
                for fd in report.per_fund_diagnosis:
                    if fd.fund_code == rs.fund_code:
                        fund_name = fd.fund_name
                        break
                actions.append({
                    "fund_code": rs.fund_code,
                    "fund_name": fund_name,
                    "action": rs.action,
                    "priority": "medium",
                    "reason": rs.reason,
                    "expected_effect": f"调整 {rs.change_pct:+.1f}%, 目标占比 {rs.target_ratio:.1f}%",
                })
        # 对没有调仓建议的基金添加 hold
        suggested_codes = {a["fund_code"] for a in actions}
        for fd in report.per_fund_diagnosis:
            if fd.fund_code not in suggested_codes and fd.debate_summary:
                ds = fd.debate_summary
                actions.append({
                    "fund_code": fd.fund_code,
                    "fund_name": fd.fund_name,
                    "action": ds.action.get("type", "hold") if ds.action else "hold",
                    "priority": "low",
                    "reason": ds.action.get("reasoning", "") if ds.action else "",
                    "expected_effect": "维持当前配置",
                })

        # ---- 组合诊断 ----
        portfolio_diag = {
            "concentration_risk": "",
            "rebalance_suggestion": "",
            "overall_assessment": "",
            "overall_health_score": None,
            "overall_health_label": "",
            "strength": "",
            "weakness": "",
        }
        if report.portfolio_diagnosis:
            pd = report.portfolio_diagnosis
            portfolio_diag["concentration_risk"] = pd.concentration_risk.get("detail", "") if pd.concentration_risk else ""
            portfolio_diag["rebalance_suggestion"] = pd.efficient_frontier_analysis.get("rebalance_direction", "") if pd.efficient_frontier_analysis else ""
            portfolio_diag["overall_assessment"] = pd.health_label or ""
            portfolio_diag["overall_health_score"] = pd.overall_health_score
            portfolio_diag["overall_health_label"] = pd.health_label or ""
            portfolio_diag["strength"] = "; ".join(pd.strengths[:3]) if pd.strengths else ""
            portfolio_diag["weakness"] = "; ".join(pd.weaknesses[:3]) if pd.weaknesses else ""

        # ---- 交叉验证 ----
        cf = report.confidence
        debate_verdict = {
            "passed": cf.overall > 0.4 if cf else True,
            "severity": "low" if cf and cf.overall > 0.5 else "medium",
            "issues": [],
            "recommendation": cf.suggestion if cf else "",
            "arbiter": None,
            # v3 新增
            "v3_overall_confidence": cf.overall if cf else 0.5,
            "v3_confidence_label": cf.overall_label if cf else "",
            "v3_warnings": cf.warnings if cf else [],
        }

        # 如果交叉验证发现了矛盾，填入 issues
        for fd in report.per_fund_diagnosis:
            if fd.debate_summary and fd.debate_summary.contradictions:
                for c in fd.debate_summary.contradictions:
                    debate_verdict["issues"].append({
                        "fund_code": fd.fund_code,
                        "finding": c.issue,
                        "fix_suggestion": c.resolution,
                    })

        # ---- 量化的真相 ----
        ground_truth = {
            "total_market_value": gt.total_market_value if gt else 0,
            "total_pnl": gt.total_pnl if gt else 0,
            "total_pnl_pct": gt.total_pnl_pct if gt else 0,
            "concentration_top3": gt.concentration.top3_pct if gt and gt.concentration else 0,
            "trend_state": "N/A",
            "trend_return": 0,
            "volatility": 0,
            "per_fund_summary": [],
            # v3 新增量化字段
            "v3_data_quality": gt.overall_data_quality if gt else "unknown",
            "v3_data_days": gt.data_days if gt else 0,
            "v3_correlation_avg": gt.correlation.avg_pairwise_corr if gt and gt.correlation else None,
            "v3_hhi": gt.concentration.hhi_index if gt and gt.concentration else None,
            "v3_frontier_quality": gt.efficient_frontier.position_quality if gt and gt.efficient_frontier else "unknown",
            "v3_frontier_distance": gt.efficient_frontier.distance_to_frontier_pct if gt and gt.efficient_frontier else None,
            "v3_optimal_weights": gt.efficient_frontier.optimal_sharpe_weights if gt and gt.efficient_frontier else {},
        }

        # 每基金量化摘要
        for fd in report.per_fund_diagnosis:
            qi = fd.ground_truth
            ground_truth["per_fund_summary"].append({
                "fund_code": fd.fund_code,
                "fund_name": fd.fund_name,
                "mv_ratio": qi.mv_ratio,
                "pnl_pct": qi.pnl_pct,
                "nav_change_pct": qi.trend.ma_deviation_pct if qi.trend else None,
                # v3 量化
                "v3_sharpe": qi.efficiency.sharpe_ratio if qi.efficiency else None,
                "v3_volatility": qi.risk.annual_volatility_pct if qi.risk else None,
                "v3_max_drawdown": qi.risk.max_drawdown_pct if qi.risk else None,
                "v3_trend_score": qi.trend.trend_strength if qi.trend else None,
                "v3_annual_return": qi.returns.annual_return_pct if qi.returns else None,
            })

        # ---- 每基金详细诊断 (v3 新增) ----
        per_fund_diagnosis = []
        for fd in report.per_fund_diagnosis:
            diag = {
                "fund_code": fd.fund_code,
                "fund_name": fd.fund_name,
            }

            if fd.trend_view:
                diag["trend"] = {
                    "score": fd.trend_view.overall_score,
                    "direction": fd.trend_view.trend_direction,
                    "strength_label": fd.trend_view.trend_strength_label,
                    "diagnosis": [
                        {"claim": d.claim, "confidence": d.confidence, "evidence": d.evidence, "sentiment": d.sentiment}
                        for d in fd.trend_view.diagnosis
                    ],
                    "key_risk": fd.trend_view.key_risk,
                    "key_opportunity": fd.trend_view.key_opportunity,
                    "confidence": fd.trend_view.confidence,
                }

            if fd.risk_view:
                diag["risk"] = {
                    "score": fd.risk_view.overall_score,
                    "level": fd.risk_view.risk_level,
                    "diagnosis": [
                        {"claim": d.claim, "confidence": d.confidence, "evidence": d.evidence, "sentiment": d.sentiment}
                        for d in fd.risk_view.diagnosis
                    ],
                    "key_risk": fd.risk_view.key_risk,
                    "key_opportunity": fd.risk_view.key_opportunity,
                    "confidence": fd.risk_view.confidence,
                }

            if fd.value_view:
                diag["value"] = {
                    "score": fd.value_view.overall_score,
                    "diagnosis": [
                        {"claim": d.claim, "confidence": d.confidence, "evidence": d.evidence, "sentiment": d.sentiment}
                        for d in fd.value_view.diagnosis
                    ],
                    "key_risk": fd.value_view.key_risk,
                    "key_opportunity": fd.value_view.key_opportunity,
                    "confidence": fd.value_view.confidence,
                }

            if fd.technical_view:
                diag["tech"] = {
                    "score": fd.technical_view.overall_score,
                    "diagnosis": [
                        {"claim": d.claim, "confidence": d.confidence, "evidence": d.evidence, "sentiment": d.sentiment}
                        for d in fd.technical_view.diagnosis
                    ],
                    "key_risk": fd.technical_view.key_risk,
                    "key_opportunity": fd.technical_view.key_opportunity,
                    "confidence": fd.technical_view.confidence,
                }

            if fd.debate_summary:
                ds = fd.debate_summary
                diag["debate"] = {
                    "health_score": ds.health_score,
                    "health_label": ds.health_label,
                    "consensus_level": ds.consensus_level,
                    "consensus_label": ds.consensus_label,
                    "contradictions": [
                        {"views": c.views, "issue": c.issue, "severity": c.severity, "resolution": c.resolution}
                        for c in ds.contradictions
                    ],
                    "strengths": ds.strengths,
                    "risks": ds.risks,
                    "action": ds.action,
                    "confidence": ds.confidence,
                    # v5: 多模型来源
                    "model_sources": ds.model_sources,
                    "model_reliability": ds.model_reliability,
                    "conflict_models": ds.conflict_models,
                }

            # 量化指标（前端展示用）
            qi = fd.ground_truth
            diag["quant"] = {
                "trend_strength": qi.trend.trend_strength,
                "sharpe": qi.efficiency.sharpe_ratio,
                "sortino": qi.efficiency.sortino_ratio,
                "volatility": qi.risk.annual_volatility_pct,
                "max_drawdown": qi.risk.max_drawdown_pct,
                "current_drawdown": qi.risk.current_drawdown_pct,
                "return_1m": qi.returns.return_1m_pct,
                "return_3m": qi.returns.return_3m_pct,
                "annual_return": qi.returns.annual_return_pct,
                "rsi": qi.momentum.rsi_14,
                "macd_signal": qi.macd.signal,
            }

            diag["degraded"] = fd.degraded
            per_fund_diagnosis.append(diag)

        # ---- 元数据 ----
        elapsed = time.time() - t0

        return {
            # v2 兼容字段
            "market_analysis": market_analysis,
            "holdings_health": holdings_health,
            "actions": actions,
            "portfolio_diagnosis": portfolio_diag,
            "debate_verdict": debate_verdict,
            "ground_truth": ground_truth,

            # v3 新增字段
            "per_fund_diagnosis": per_fund_diagnosis,

            # 元数据
            "generated_at": report.generated_at,
            "model": f"FundAnalyzer v3 ({report.model})",
            "model_chain": report.model_chain,
            "model_roles": getattr(report, 'model_roles', {}),
            "portfolio_date": str(date.today()),
            "analysis_duration_seconds": round(elapsed, 1),
            "data_duration_seconds": report.data_duration_seconds,
            "llm_call_count": report.llm_call_count,
            "llm_failure_count": report.llm_failure_count,
            "llm_fallback_count": report.llm_fallback_count,
            "degradation": {
                "any": report.degradation.any_degraded if report.degradation else False,
                "impact": report.degradation.impact if report.degradation else "none",
                "steps": report.degradation.degraded_steps if report.degradation else [],
            },
            "completeness": {
                "pct": report.completeness.completeness_pct if report.completeness else 100,
                "data_quality": report.completeness.data_quality_label if report.completeness else "unknown",
            },
            "engine_version": "v3",
        }

    # ═══════════════════════════════════════════════════
    # v2 兼容 — 旧引擎保留
    # ═══════════════════════════════════════════════════

    def _step1_per_fund_analysis_v2(self, facts: dict) -> list[dict]:
        """v2 逐基金分析 (简化版, 不使用 LLM)"""
        holdings = facts["per_fund"]
        results = []
        for h in holdings:
            pnl = h["pnl_pct"]
            score = 70
            if pnl > 5: score = 85
            elif pnl > 0: score = 75
            elif pnl > -5: score = 55
            elif pnl > -10: score = 40
            else: score = 25
            if h["is_money_fund"]: score = 88
            results.append({
                "fund_code": h["fund_code"],
                "fund_name": h["fund_name"],
                "health_score": score,
                "health_diagnosis": f"v2 简化分析: 盈亏 {pnl:+.1f}%",
                "risk_factors": [f"盈亏 {pnl:+.1f}%"],
                "optimistic_factors": [],
                "data_citations": [],
                "key_metric": "盈亏百分比",
                "fund_type": h.get("fund_type", "未知"),
                "current_mv": h["current_mv"],
                "mv_ratio": h["mv_ratio"],
                "pnl_pct": pnl,
                "nav_change_pct": h.get("nav_change_pct"),
                "is_money_fund": h["is_money_fund"],
            })
        return results

    def _step2_synthesis_v2(self, facts: dict, fund_analyses: list[dict]) -> dict:
        """v2 组合综合诊断 (简化版)"""
        actions = []
        for fa in fund_analyses:
            if fa.get("is_money_fund"):
                action, priority = "hold", "low"
            elif fa["pnl_pct"] > 5: action, priority = "add", "medium"
            elif fa["pnl_pct"] > -5: action, priority = "hold", "medium"
            elif fa["pnl_pct"] > -15: action, priority = "watch", "medium"
            else: action, priority = "reduce", "high"
            actions.append({
                "fund_code": fa["fund_code"], "fund_name": fa["fund_name"],
                "action": action, "priority": priority,
                "reason": f"v2: 盈亏 {fa['pnl_pct']:+.1f}%",
                "expected_effect": "",
            })
        return {
            "market_analysis": {
                "trend": facts["trend"]["state"],
                "key_signals": [],
                "overall": f"v2 自动诊断 (组合盈亏 {facts['summary']['total_pnl_pct']:+.1f}%)",
            },
            "portfolio_diagnosis": {
                "concentration_risk": f"前3持仓 {facts['concentration']['top3_ratio']}%",
                "rebalance_suggestion": "",
                "overall_assessment": f"v2 简化模式",
                "strength": "",
                "weakness": "",
            },
            "actions": actions,
        }

    def _step4_assemble_v2(self, facts, fund_analyses, synthesis, debate, t0) -> dict:
        """v2 组装"""
        return {
            "market_analysis": synthesis["market_analysis"],
            "holdings_health": [
                {"fund_code": fa["fund_code"], "fund_name": fa["fund_name"],
                 "health_score": fa["health_score"], "health_diagnosis": fa["key_metric"],
                 "concerns": "; ".join(fa.get("risk_factors", [])[:3]),
                 "suggestion": next((a["action"] for a in synthesis["actions"] if a["fund_code"] == fa["fund_code"]), "hold"),
                 "data_citations": []}
                for fa in fund_analyses
            ],
            "actions": synthesis["actions"],
            "portfolio_diagnosis": synthesis["portfolio_diagnosis"],
            "debate_verdict": {"passed": True, "severity": "none", "issues": [], "arbiter": None},
            "ground_truth": {
                "total_market_value": facts["summary"]["total_market_value"],
                "total_pnl": facts["summary"]["total_pnl"],
                "total_pnl_pct": facts["summary"]["total_pnl_pct"],
                "concentration_top3": facts["concentration"]["top3_ratio"],
                "trend_state": facts["trend"]["state"],
                "trend_return": facts["trend"].get("long_return_pct", 0),
                "volatility": facts["trend"].get("volatility_pct", 0),
                "per_fund_summary": [
                    {"fund_code": f["fund_code"], "fund_name": f["fund_name"],
                     "mv_ratio": f["mv_ratio"], "pnl_pct": f["pnl_pct"],
                     "nav_change_pct": f.get("nav_change_pct")}
                    for f in facts["per_fund"]
                ],
            },
            "generated_at": datetime.now().isoformat(),
            "model": "v2-legacy",
            "model_chain": {},
            "portfolio_date": str(date.today()),
            "analysis_duration_seconds": round(time.time() - t0, 1),
            "engine_version": "v2",
        }

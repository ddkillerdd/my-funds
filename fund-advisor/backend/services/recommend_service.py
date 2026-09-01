"""
Recommendation Service (RFC-010): 择时 + 荐基 桥接层.

Delegates the numeric/quant work to fund-analyzer's engines:
  - engine/timing.py        -> 入场择时
  - engine/screen_runner.py -> 荐基打分（端到端拉取+量化+排序）

This file only does: DB 数据适配 (持仓NAV作分散参照)、engine import、
评分结果序列化为 API schema dict. 评分永远由 Python 完成，LLM 只做解读。
"""

import asyncio
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.engine_bridge import ensure_engine_path

# 确保可以 import fund_analyzer（与 advisor_service 相同路径注入）
ensure_engine_path()

from engine.models import QuantIndicators  # noqa: E402
from engine.quant import compute_all  # noqa: E402

logger = logging.getLogger(__name__)

ACTION_LABELS = {
    "avoid": "暂不买入",
    "wait": "继续等待",
    "staged_entry": "分批建仓",
    "now_entry": "可分批买入",
    "buy_now": "可以买入",
    "dca": "建议定投",
}


class RecommendService:
    """投资推荐桥接服务 (择时 + 荐基)。"""

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────
    #  工具：从 DB 读取持仓 NAV（分散化参照）
    # ─────────────────────────────────────────────
    def _portfolio_navs(self, days: int = 250) -> List[List[float]]:
        """Read current active holdings' NAV series as NavPoint lists.

        返回 List[List[NavPoint]](引擎 run_screener 契约);
        每个元素是 NavPoint(date, nav)。
        """
        from engine.models import NavPoint
        from backend.services.nav_service import NavService
        ns = NavService(self.db)
        codes = ns.get_held_fund_codes()
        out: List[List[NavPoint]] = []
        for code in codes:
            rows = ns.get_nav_history(code, days=days)
            series = []
            for r in rows:
                if r.get("unit_nav") is None:
                    continue
                series.append(NavPoint(date=str(r.get("date") or ""), nav=float(r["unit_nav"])))
            if series:
                out.append(series)
        return out

    # ─────────────────────────────────────────────
    #  ① 入场择时
    # ─────────────────────────────────────────────
    def get_timing(self, fund_code: str, fund_name: Optional[str] = None,
                   playbook: str = "auto") -> dict:
        """Compute entry timing recommendation for one fund."""
        try:
            from engine.screen_runner import fetch_fund_nav_full
            from engine.market_data import (
                fetch_fund_detail, extract_fund_info,
                nav_based_valuation_percentile,
            )
            from engine.timing import compute_entry_recommendation

            # 拉取 NAV + 详情（内存受限：只处理这一只）
            async def _load():
                import httpx
                async with httpx.AsyncClient(
                    timeout=30, http2=False,
                    headers={"User-Agent": "Mozilla/5.0",
                             "Referer": "https://fund.eastmoney.com/"},
                ) as client:
                    navs = await fetch_fund_nav_full(client, fund_code)
                    detail = await fetch_fund_detail(client, fund_code)
                    return navs, detail

            navs, detail = asyncio.run(_load())

            # 附加估值分位（NAV 历史代理），供 valuation 因子
            trend = (detail or {}).get("nav_trend") or []
            vp = nav_based_valuation_percentile(trend)
            info = extract_fund_info(detail)
            name = info.get("fund_name") or fund_name or fund_code

            if not navs or len(navs) < 40:
                return {
                    "fund_code": fund_code, "fund_name": name,
                    "recommendation": "wait", "confidence_pct": 0.0,
                    "action_label": "数据不足",
                    "risk_gate_status": "blocked",
                    "risk_gate_reason": f"NAV 数据不足({len(navs)}天)无法择时",
                    "timing_factors": [], "suggested_dca": None,
                    "notes": ["数据不足，无法给出择时建议"],
                    "data_quality": "insufficient", "error": "nav_data_insufficient",
                }

            qi = compute_all(
                # 用 FundHolding 承载 nav 历史（仅取量化所需字段）
                _make_fund_holding(fund_code, name, navs)
            )
            if vp is not None:
                qi._valuation_percentile = vp

            rec = compute_entry_recommendation(
                qi, budget_pct=10.0,
                override_valuation_percentile=vp,
            )

            # 序列化
            factors = [
                {
                    "name": f.name,
                    "value": None,
                    "score": f.score,
                    "evidence": f.evidence,
                }
                for f in rec.factors
            ]
            dca = None
            if rec.dca and rec.dca.enabled:
                dca = {
                    "method": rec.dca.method,
                    "frequency": rec.dca.frequency,
                    "base_amount_pct": rec.dca.base_amount_pct,
                    "note": rec.dca.note,
                }

            gate = rec.risk_gate or {}
            reasons = gate.get("reasons") or (gate.get("reason") or "")
            if isinstance(reasons, list):
                reason_str = "；".join(reasons)
            else:
                reason_str = str(reasons)
            return {
                "fund_code": fund_code,
                "fund_name": name,
                "recommendation": rec.window,
                "confidence_pct": round(rec.confidence * 100, 1),
                "action_label": ACTION_LABELS.get(rec.window, rec.window),
                "risk_gate_status": "blocked" if gate.get("blocked") else "passed",
                "risk_gate_reason": reason_str,
                "timing_factors": factors,
                "suggested_dca": dca,
                "notes": rec.notes + [f"NAV历史{len(navs)}天"],
                "data_quality": rec.data_quality,
                "error": None,
            }
        except Exception as e:
            logger.exception("get_timing failed for %s", fund_code)
            return {
                "fund_code": fund_code, "fund_name": fund_name or fund_code,
                "recommendation": "wait", "confidence_pct": 0.0,
                "action_label": "计算失败", "risk_gate_status": "blocked",
                "risk_gate_reason": str(e)[:200], "timing_factors": [],
                "suggested_dca": None, "notes": [f"择时计算失败: {e}"],
                "data_quality": "error", "error": str(e)[:200],
            }

    # ─────────────────────────────────────────────
    #  ② 荐基打分
    # ─────────────────────────────────────────────
    def run_screen(
        self,
        candidates: List[dict],
        budget_pct: float = 10.0,
        top_n: int = 5,
        portfolio_holdings_info: Optional[str] = None,
        with_ai_explanation: bool = False,
        use_current_portfolio: bool = True,
    ) -> dict:
        """Score & rank a candidate fund pool (荐基)."""
        try:
            import asyncio
            from engine.screen_runner import (
                run_screener, run_screener_with_explanation,
            )

            # 候选 (code, name)
            cands = [
                (c.get("fund_code"), c.get("fund_name") or c.get("fund_code"))
                for c in candidates if c.get("fund_code")
            ]
            if not cands:
                return {"candidates_scanned": 0, "recommendations": [],
                        "notes": ["未提供有效候选基金"], "error": "no_candidates",
                        "data_quality": "unknown"}

            # 若开启使用当前持仓做分散化参照
            pf_navs = None
            if use_current_portfolio:
                pf_navs = self._portfolio_navs(days=250)  # list of float series
                if not pf_navs:
                    pf_navs = None

            with_ai = with_ai_explanation
            if with_ai:
                from backend.config import get_settings
                s = get_settings()
                res = asyncio.run(run_screener_with_explanation(
                    cands,
                    api_base=s.NEWAPI_BASE_URL,
                    api_key=s.NEWAPI_API_KEY,
                    model="deepseek-ai/deepseek-v4-flash",
                    portfolio_navs=pf_navs,
                    budget_pct=budget_pct,
                    top_n=top_n,
                    portfolio_holdings_info=portfolio_holdings_info,
                ))
            else:
                res = asyncio.run(run_screener(
                    cands,
                    portfolio_navs=pf_navs,
                    budget_pct=budget_pct,
                    top_n=top_n,
                ))

            recommendations = []
            for r in res.recommendations:
                recommendations.append({
                    "fund_code": r.fund_code,
                    "fund_name": r.fund_name,
                    "fund_type": r.fund_type,
                    "total_score": r.total_score,
                    "style_tag": r.style_tag,
                    "correlation_with_portfolio": r.correlation_with_portfolio,
                    "suggested_ratio_pct": r.suggested_ratio_pct,
                    "timing_window": r.timing_window,
                    "timing_score": r.timing_score,
                    "factor_scores": [
                        {"factor": f.factor, "score": f.score,
                         "evidence": f.evidence, "weight": f.weight}
                        for f in r.factor_scores
                    ],
                    "ai_explanation": r.ai_explanation,
                    "data_quality": r.data_quality,
                    "disclaimer_note": r.disclaimer_note,
                })

            return {
                "candidates_scanned": res.candidates_scanned,
                "portfolio_context": res.portfolio_context or {},
                "recommendations": recommendations,
                "notes": res.notes,
                "data_quality": res.data_quality,
                "error": None,
            }
        except Exception as e:
            logger.exception("run_screen failed")
            return {
                "candidates_scanned": 0, "portfolio_context": {},
                "recommendations": [], "notes": [f"荐基计算失败: {e}"],
                "data_quality": "error", "error": str(e)[:200],
            }

def _make_fund_holding(fund_code, fund_name, navs):
    """Build a lightweight FundHolding for QuantIndicators computation."""
    from engine.models import FundHolding, NavPoint
    nav_points = [NavPoint(date=getattr(p, "date", "") or "", nav=float(p.nav))
                  for p in navs]
    return FundHolding(
        fund_code=fund_code, fund_name=fund_name,
        current_mv=0.0, cost=0.0, nav_history=nav_points,
    )

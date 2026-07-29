"""AI Advisor Service - core AI analysis engine.

Calls NewAPI (NVIDIA NIM free tier) for portfolio analysis.
Produces structured JSON output for the AdvisorView frontend.
"""

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.portfolio_snapshot import PortfolioSnapshot
from backend.models.nav_history import FundNavHistory

logger = logging.getLogger(__name__)

# Default analysis model (can be overridden)
DEFAULT_MODEL = "stepfun-ai/step-3.7-flash"


class AdvisorService:
    """AI-powered investment advisor service."""

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    # ---------- Public API ----------

    def analyze(self, model: str = DEFAULT_MODEL) -> dict:
        """Run a full portfolio analysis and return structured results."""
        portfolio_data = self._build_portfolio_context()
        prompt = self._build_analysis_prompt(portfolio_data)
        raw = self._call_llm(prompt, model)
        try:
            result = self._parse_result(raw)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Failed to parse LLM result: {e}")
            result = self._build_error_result(str(e))
        result["generated_at"] = datetime.now().isoformat()
        result["model"] = model
        result["portfolio_date"] = str(date.today())
        return result

    # ---------- Context Building ----------

    def _get_money_fund_codes(self) -> set[str]:
        """Get set of fund codes that are money market funds."""
        rows = self.db.execute(
            select(Fund.fund_code).where(Fund.fund_type == "货币型")
        ).scalars().all()
        return set(rows)

    def _get_recent_snapshots(self, days: int = 60) -> list[dict]:
        """Get recent portfolio snapshots for trend analysis."""
        cutoff = date.today()
        rows = self.db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.snapshot_date <= cutoff)
            .order_by(PortfolioSnapshot.snapshot_date.desc())
            .limit(days)
        ).scalars().all()
        return [
            {
                "date": str(r.snapshot_date),
                "total_mv": float(r.total_market_value) if r.total_market_value else 0,
                "daily_pnl": float(r.daily_pnl) if r.daily_pnl else 0,
                "nav": float(r.portfolio_nav) if r.portfolio_nav else 0,
            }
            for r in reversed(rows)
        ]

    def _build_portfolio_context(self) -> dict:
        """Build structured context from portfolio data."""
        money_fund_codes = self._get_money_fund_codes()
        holdings = self.db.execute(
            select(FundHolding, Fund)
            .outerjoin(Fund, FundHolding.fund_code == Fund.fund_code)
            .where(FundHolding.status == 1)
        ).all()

        holding_list = []
        total_mv = Decimal("0")
        total_cost = Decimal("0")

        for holding, fund in holdings:
            shares = holding.shares or Decimal("0")
            if holding.fund_code in money_fund_codes:
                mv = shares
            elif fund and fund.latest_nav and shares:
                mv = shares * fund.latest_nav
            else:
                mv = holding.market_value or Decimal("0")

            cost_mv = Decimal("0")
            if holding.cost_nav and shares:
                cost_mv = shares * holding.cost_nav

            total_mv += mv
            total_cost += cost_mv

            holding_list.append({
                "fund_code": holding.fund_code,
                "fund_name": holding.fund_name,
                "fund_type": fund.fund_type if fund else None,
                "platform": holding.platform,
                "shares": float(shares),
                "latest_nav": float(fund.latest_nav) if fund and fund.latest_nav else None,
                "nav_change_pct": float(fund.nav_change_pct) if fund and fund.nav_change_pct else None,
                "cost_nav": float(holding.cost_nav) if holding.cost_nav else None,
                "current_mv": float(mv),
                "cost_mv": float(cost_mv),
                "is_money_fund": holding.fund_code in money_fund_codes,
            })

        total_pnl = float(total_mv - total_cost)
        total_pnl_pct = (total_pnl / float(total_cost) * 100) if total_cost > 0 else 0

        snapshots = self._get_recent_snapshots()

        # Latest snapshot nav
        latest_nav = None
        if snapshots:
            latest_nav = snapshots[-1].get("nav")

        return {
            "total_market_value": float(total_mv),
            "total_cost": float(total_cost),
            "total_pnl": total_pnl,
            "total_pnl_pct": round(total_pnl_pct, 2),
            "holding_count": len(holding_list),
            "last_nav": latest_nav,
            "snapshots": snapshots,
            "holdings": holding_list,
        }

    # ---------- Prompt Building ----------

    def _build_analysis_prompt(self, context: dict) -> str:
        """Build structured prompt for LLM analysis."""
        return f"""你是一个专业的基金投资顾问，请根据以下持仓数据为用户生成分析报告。

## 持仓概况
- 总市值: {context['total_market_value']:.2f} 元
- 总投入成本: {context['total_cost']:.2f} 元
- 总盈亏: {context['total_pnl']:.2f} 元 ({context['total_pnl_pct']}%)
- 持仓数量: {context['holding_count']} 笔
- 最近组合净值: {context['last_nav']}

## 持仓明细
{json.dumps(context['holdings'], ensure_ascii=False, indent=2)}

## 近60日组合净值趋势
{json.dumps(context['snapshots'], ensure_ascii=False, indent=2)}

请按以下 JSON 格式回答，不要输出其他内容：

```json
{{
  "market_analysis": {{
    "trend": "震荡/上涨/下跌/震荡偏强/震荡偏弱",
    "key_signals": ["信号1", "信号2"],
    "overall": "简短的市场整体判断（30字以内）"
  }},
  "holdings_health": [
    {{
      "fund_code": "基金代码",
      "fund_name": "基金名称",
      "health_score": 0-100,
      "concerns": "主要风险，没有则留空",
      "suggestion": "处理建议，没有则留空"
    }}
  ],
  "actions": [
    {{
      "fund_code": "基金代码",
      "fund_name": "基金名称",
      "action": "hold/reduce/add/watch",
      "reason": "理由",
      "priority": "high/medium/low"
    }}
  ],
  "portfolio_diagnosis": {{
    "concentration_risk": "集中度风险描述",
    "rebalance_suggestion": "调仓建议",
    "overall_assessment": "整体评价"
  }}
}}
```

注意：
1. health_score 0-100，越高越健康
2. action: hold=持有, reduce=减仓, add=加仓, watch=关注
3. 货币基金不参与加减仓判断
4. 如果某只基金亏损较大或估值偏高，应给出具体建议
5. 集中度风险主要看前3大持仓占比
"""

    # ---------- LLM Call ----------

    def _call_llm(self, prompt: str, model: str) -> str:
        """Call NewAPI with the given prompt."""
        if not self.settings.NEWAPI_BASE_URL or not self.settings.NEWAPI_API_KEY:
            logger.warning("NewAPI not configured, using fallback analysis")
            return self._build_fallback_result()

        url = f"{self.settings.NEWAPI_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.NEWAPI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 4096,
        }

        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                msg = data["choices"][0]["message"]
                # NVIDIA NIM 推理模型: content 可能为 null, 实际回答在 reasoning 字段
                content = msg.get("content") or msg.get("reasoning") or ""
                return content
        except httpx.TimeoutException:
            logger.error(f"NewAPI timeout for model {model}")
            return self._build_fallback_result()
        except Exception as e:
            logger.error(f"NewAPI call failed: {e}")
            return self._build_fallback_result()

    # ---------- Result Parsing ----------

    def _parse_result(self, raw: str) -> dict:
        """Extract JSON from LLM response (handles markdown code fences)."""
        # Remove markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            # Find the first { and last }
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                raw = raw[start : end + 1]

        return json.loads(raw)

    # ---------- Fallback ----------

    def _build_fallback_result(self) -> str:
        """Return a fallback JSON string when LLM is unavailable."""
        return json.dumps({
            "market_analysis": {
                "trend": "无法获取",
                "key_signals": [],
                "overall": "AI 分析服务暂时不可用，请稍后再试。"
            },
            "holdings_health": [],
            "actions": [],
            "portfolio_diagnosis": {
                "concentration_risk": "无法分析",
                "rebalance_suggestion": "无法分析",
                "overall_assessment": "AI 分析服务暂时不可用，请检查 NewAPI 配置或稍后再试。"
            }
        }, ensure_ascii=False)

    def _build_error_result(self, error_msg: str) -> dict:
        return json.loads(self._build_fallback_result())

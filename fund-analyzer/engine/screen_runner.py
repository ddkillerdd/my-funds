"""
FundAnalyzer — Screener Runner (RFC-008 荐基端到端)

Brings together the Market Data Layer + quant computation + screener scoring:

    fetch_candidates()  ─┐
      (eastmoney NAV)    ├→ compute per-fund QuantIndicators
    fetch_details()      ─┤     (bounded memory, one at a time)
    fetch_indexes()      ─┘→ ScreenContext(portfolio, style indexes)
                              → screen_funds() → ranked recommendations
                              → (optional) AI explanation per top pick

Server reality (3.6GB RAM / 0 swap): candidates are processed sequentially and
their raw NAV lists are released after indicator computation (no full-correlation
matrix in memory). Disk cache under data_cache/ avoids re-fetching.

NOTE: this module only supplies/glues data + numeric scoring. LLM explanation is
optional and intentionally placed AFTER scoring so a model glitch can never
change the rank (防幻觉: LLM 只解读不评分).
"""

from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from .market_data import (
    INDEXES,
    batch_fetch_indexes,
    fetch_fund_detail,
    extract_fund_info,
)
from .models import (
    FundHolding,
    NavPoint,
    QuantIndicators,
)
from .quant import compute_all
from .screener import (
    ScreenContext,
    ScreenerResult,
    screen_funds,
)

logger = logging.getLogger(__name__)

# 东财 fund NAV kline API (same shape as existing nav_fetcher used by fund-advisor)
_NAV_KLINE_URL = "https://api.fund.eastmoney.com/f10/lsjz"
_CHUNK_SIZE = 250          # 东财 returns newer-first chunks of this size


async def fetch_fund_nav_full(
    client: "httpx.AsyncClient",
    fund_code: str,
    max_days: int = 1500,
) -> List[NavPoint]:
    """Fetch full NAV history (oldest-first) for a fund, memory-bounded.

    Uses the single-request pingzhongdata JS endpoint (Data_netWorthTrend),
    which returns the whole history in one shot — far cheaper than paginating
    the rate-capped lsjz API (20 rows/page). Falls back to lsjz pagination.
    """
    from .market_data import fetch_fund_detail
    try:
        detail = await fetch_fund_detail(client, fund_code, use_cache=True)
        trend = (detail or {}).get("nav_trend") or []
        navs = []
        for p in trend:
            if not isinstance(p, dict) or p.get("y") is None:
                continue
            try:
                x = p.get("x")
                if isinstance(x, (int, float)) and x > 1e6:
                    # millisecond epoch -> YYYY-MM-DD
                    import datetime as _dt
                    date_str = _dt.datetime.utcfromtimestamp(x / 1000).strftime("%Y-%m-%d")
                else:
                    date_str = str(x or "")
                navs.append(NavPoint(date=date_str, nav=float(p["y"])))
            except (TypeError, ValueError, OverflowError):
                continue
        if len(navs) >= 30:
            return navs[-max_days:]
        logger.info("pingzhongdata nav empty for %s, fallback to lsjz", fund_code)
    except Exception as e:
        logger.warning("pingzhongdata nav failed for %s: %s", fund_code, e)
    return await _fetch_nav_lsjz(client, fund_code, max_days=max_days)


async def _fetch_nav_lsjz(client, fund_code: str, max_days: int = 1500) -> List[NavPoint]:
    """Fallback: paginate the lsjz API (capped at 20 rows/page)."""
    navs: List[NavPoint] = []
    page = 1
    while True:
        params = {
            "fundCode": fund_code,
            "pageIndex": str(page),
            "pageSize": "20",
        }
        try:
            resp = await client.get(_NAV_KLINE_URL, params=params)
            resp.raise_for_status()
            data = (resp.json().get("Data") or {}).get("LSJZList") or []
        except Exception as e:
            logger.warning("_fetch_nav_lsjz %s page %d failed: %s",
                           fund_code, page, e)
            break
        if not data:
            break
        page_navs = []
        for row in data:
            nav_str = row.get("DWJZ")
            if not nav_str:
                continue
            try:
                page_navs.append(NavPoint(date=row.get("FSRQ", ""),
                                          nav=float(nav_str)))
            except (TypeError, ValueError):
                continue
        if not page_navs:
            break
        # 东财 returns newest-first; prepend to build oldest-first
        navs = page_navs + navs
        if len(page_navs) < 20 or len(navs) >= max_days:
            break
        page += 1
        if page > 80:  # 80*20=1600 days safety cap
            break
    return navs[-max_days:]


def _navs_to_holding(code: str, name: str, navs: List[NavPoint],
                     ref_mv: float = 0.0) -> FundHolding:
    """Build a FundHolding from raw navs (ref_mv is only a placeholder)."""
    return FundHolding(
        fund_code=code,
        fund_name=name,
        current_mv=ref_mv,
        cost=ref_mv,
        nav_history=navs,
    )


async def build_candidates_indicators(
    client: "httpx.AsyncClient",
    codes_names: List[Tuple[str, str]],
    max_days: int = 1000,
) -> Tuple[List[QuantIndicators], Dict[str, Dict]]:
    """Fetch NAV + details for a list of (code, name), compute indicators.

    Returns (list_of_QuantIndicators, {code: detail_info}). Memory-bounded:
    each fund's navs are released after compute_all.
    """
    qis: List[QuantIndicators] = []
    details: Dict[str, Dict] = {}
    for code, name in codes_names:
        try:
            navs = await fetch_fund_nav_full(client, code, max_days=max_days)
            if len(navs) < 30:
                logger.warning("候选 %s nav 数据不足(%d 天)，跳过", code, len(navs))
                continue
            qi = compute_all(_navs_to_holding(code, name, navs))
            qi._navs = list(navs)  # attach a copy for diversification/style
            qis.append(qi)
            details[code] = extract_fund_info(
                await fetch_fund_detail(client, code))
            # release raw series as soon as possible
            navs.clear()
        except Exception as e:
            logger.warning("候选 %s 处理失败: %s", code, e)
            continue
    return qis, details


async def run_screener(
    candidates: List[Tuple[str, str]],
    portfolio_navs: Optional[List[List[NavPoint]]] = None,
    budget_pct: float = 10.0,
    top_n: int = 10,
    style_index_names: Optional[List[str]] = None,
) -> ScreenerResult:
    """End-to-end screening.

    Args:
        candidates: list of (fund_code, fund_name) to evaluate.
        portfolio_navs: existing holdings' NAV series (NavPoint lists) for
            diversification scoring.
        budget_pct: base single-position ratio.
        top_n: max recommendations.
        style_index_names: index names for style attribution
            (defaults to 沪深300/中证500/创业板指 etc.).

    Returns:
        ScreenerResult with scored recommendations.
    """
    async with _client() as client:
        # style indexes
        style_indexes: Dict[str, List[Tuple[str, float]]] = {}
        names = style_index_names or list(INDEXES.keys())[:4]
        idx_map = await batch_fetch_indexes(client, names, limit=300)
        for idx_name in names:
            if idx_map.get(idx_name):
                style_indexes[idx_name] = idx_map[idx_name]

        # candidate indicators + details
        qis, details = await build_candidates_indicators(client, candidates)

        # portfolio context (NavPoint -> floats)
        pf_floats: List[List[float]] = []
        for series in portfolio_navs or []:
            row = [float(p.nav) for p in series if p.nav is not None]
            if row:
                pf_floats.append(row)

        ctx = ScreenContext(
            portfolio_navs=pf_floats,
            style_indexes={
                k: v for k, v in {
                    **style_indexes,
                    # also register style boxes from INDEXES
                }.items()
            },
        )

        result = screen_funds(qis, ctx, details=details, navs_map=None,
                              budget_pct=budget_pct, top_n=top_n)
        return result


def _client():
    import httpx
    return httpx.AsyncClient(timeout=30, http2=False,
                             headers={"User-Agent": "Mozilla/5.0",
                                      "Referer": "https://fund.eastmoney.com/"})


async def run_screener_with_explanation(
    candidates: List[Tuple[str, str]],
    api_base: str,
    api_key: str,
    model: str,
    portfolio_navs: Optional[List[List[NavPoint]]] = None,
    budget_pct: float = 10.0,
    top_n: int = 5,
    portfolio_holdings_info: Optional[str] = None,
) -> ScreenerResult:
    """Run screener then attach an LLM explanation to the top picks.

    LLM explains the quant facts ONLY — it never changes scores (防幻觉).
    Explanation is appended to rec.ai_explanation.
    """
    result = await run_screener(candidates, portfolio_navs=portfolio_navs,
                                budget_pct=budget_pct, top_n=top_n)
    if not result.recommendations:
        return result

    from .llm_client import LLMClient, LLMConfig
    cfg = LLMConfig(api_base=api_base, api_key=api_key, primary_model=model)
    llm = LLMClient(cfg)

    # Build a compact fact sheet for the top picks
    lines = [f"当前组合上下文: {portfolio_holdings_info or '未提供'}"]
    for r in result.recommendations[:3]:
        fts = " | ".join(
            f"{fs.factor}={fs.score:.0f}" for fs in r.factor_scores if fs.weight > 0)
        lines.append(
            f"- {r.fund_name}({r.fund_code}) 总分{r.total_score} 风格[{r.style_tag}] "
            f"相关性{r.correlation_with_portfolio} 建议配比{r.suggested_ratio_pct}% "
            f"因子{{{fts}}}"
        )
    facts = "\n".join(lines)
    prompt = (
        "以下是量化荐基引擎给出的排名与因子得分(仅供参考，非投资建议)。"
        "请用中文为前几名各写一句不超过40字的解读，说明它适合什么样的投资者，"
        "不要改动任何分数，不要给出买卖指令：\n" + facts
    )
    try:
        resp = llm.call(prompt, temperature=0.3, max_tokens=400,
                        step_label="screener_explain")
        text = resp or ""
        # naive split by bullets
        picks = [l for l in text.splitlines() if l.strip().startswith(("-", "•", "1.", "2."))]
        for i, r in enumerate(result.recommendations[:3]):
            if i < len(picks):
                r.ai_explanation = picks[i].lstrip("-• 0123456789.").strip()
    except Exception as e:
        logger.warning("screener AI explanation failed: %s", e)
    return result

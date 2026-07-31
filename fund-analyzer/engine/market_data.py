"""
FundAnalyzer — Market Data Layer (RFC-009 section 3.1 / Phase C)

Extends the East Money data source with:
  - Index NAV (benchmark & style attribution)
  - Fund scale / type / manager detail
  - Valuation percentile (NAV-history-based fallback, no external PE dependency)

Design constraints (server reality: 3.6GB RAM, 0 swap, 24GB disk):
  - Pull-on-demand only (never a resident poller)
  - Disk cache under data_cache/ to avoid re-fetching / getting IP-banned
  - Bounded memory: process one fund's series at a time
  - All failures degrade gracefully to partial data (never crash the pipeline)

Layering rule (RFC-009): this module ONLY supplies data. Scoring / reasoning
happens in engine/timing.py (valuation factor) & engine/screener.py (peer).
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import re
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---- East Money endpoints ----
HISTORY_NAV_URL = "https://api.fund.eastmoney.com/f10/lsjz"        # fund NAV
INDEX_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"  # index klines
FUND_DETAIL_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"      # detail/buildings

# Index definitions: name -> (secid_market, secid_code)
INDEXES = {
    "沪深300": ("1", "000300"),
    "中证500": ("1", "000905"),
    "上证50": ("1", "000016"),
    "创业板指": ("0", "399006"),
    "中证1000": ("1", "000852"),
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data_cache")
# cap cache staleness (seconds) — index klines refresh daily; detail 1d; value ok
CACHE_TTL = {
    "index": 12 * 3600,
    "detail": 24 * 3600,
    "valuation": 24 * 3600,
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0.0.0",
]


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def _cache_get(key: str, max_age: float) -> Optional[dict]:
    p = _cache_path(key)
    try:
        if not os.path.exists(p):
            return None
        age = os.path.getmtime(p)
        import time
        if time.time() - age > max_age:
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_set(key: str, data: dict) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.debug("cache write failed for %s: %s", key, e)


def _headers() -> dict:
    import random as _r
    return {
        "User-Agent": _r.choice(USER_AGENTS),
        "Referer": "https://fund.eastmoney.com/",
    }


# ============================================================
#  INDEX NAV
# ============================================================

async def fetch_index_nav(
    client: httpx.AsyncClient,
    index_name: str = "沪深300",
    limit: int = 500,
    use_cache: bool = True,
) -> Optional[List[Tuple[str, float]]]:
    """Fetch index close points: list of (date, close).

    Args:
        index_name: key of INDEXES.
        limit: max recent daily bars to return.

    Returns:
        [(date, close), ...] oldest→newest, or None on failure.
    """
    if index_name not in INDEXES:
        logger.warning("unknown index %s", index_name)
        return None
    market, code = INDEXES[index_name]

    cache_key = f"index_{market}_{code}"
    cached = _cache_get(cache_key, CACHE_TTL["index"]) if use_cache else None
    if cached:
        pts = cached.get("points", [])
        return [(d, float(c)) for d, c in pts[-limit:]]

    params = {
        "secid": f"{market}.{code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56",
        "klt": "101",            # daily
        "fqt": "1",
        "end": "20500101",
        "lmt": str(max(limit, 600)),   # cache generously; slice on read
    }
    try:
        resp = await client.get(INDEX_KLINE_URL, params=params, headers=_headers())
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") or {}
        klines = data.get("klines") or []
        points = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 5:
                points.append((parts[0], float(parts[2])))  # date, close
        if points:
            # cache the fuller set (up to 600) so smaller limit reads reuse it
            _cache_set(cache_key, {"points": points})
        return points[-limit:] if points else None
    except Exception as e:
        logger.warning("fetch_index_nav failed for %s: %s", index_name, e)
        return None


# ============================================================
#  FUND DETAIL (scale / type)
# ============================================================

async def fetch_fund_detail(
    client: httpx.AsyncClient,
    fund_code: str,
    use_cache: bool = True,
) -> Optional[Dict]:
    """Fetch fund scale/type metadata from pingzhongdata JS.

    Returns dict with: fund_name, fund_type, scale_wan, manager, established,
    or None on failure.
    """
    key = f"detail_{fund_code}"
    cached = _cache_get(key, CACHE_TTL["detail"]) if use_cache else None
    if cached:
        return cached

    url = FUND_DETAIL_URL.format(code=fund_code)
    try:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        text = resp.text

        result: Dict = {"fund_code": fund_code}
        for var, field in [
            ("fS_name", "fund_name"),
            ("fS_code", "code"),
            ("Data_currentFundManager", "manager"),
            ("Data_currentScal", "scale_wan"),
            ("Data_netWorthTrend", "nav_trend"),
            ("Data_assetAllocation", "asset_alloc"),
            ("Data_stockCodes", "stock_codes"),
        ]:
            m = re.search(rf"{var}\s*=\s*(.*?);", text, re.DOTALL)
            if m:
                raw = m.group(1).strip()
                try:
                    result[field] = json.loads(raw)
                except Exception:
                    # maybe quoted single-string assignment
                    mm = re.match(r"^['\"](.*)['\"]$", raw)
                    result[field] = mm.group(1) if mm else None

        if not result.get("nav_trend") and not result.get("fund_name"):
            logger.debug("fund detail empty for %s", fund_code)
            return None

        _cache_set(key, result)
        return result
    except Exception as e:
        logger.warning("fetch_fund_detail failed for %s: %s", fund_code, e)
        return None


def extract_fund_info(detail: Optional[Dict]) -> Dict:
    """Parse raw fund detail into a compact, JSON-safe info dict."""
    if not detail:
        return {}
    info: Dict = {
        "fund_code": detail.get("code") or "",
        "fund_name": detail.get("fund_name", ""),
    }
    # scale (元) — try manager.fundSize first, then legacy scale_wan
    mgr = detail.get("manager")
    info["manager"] = ""
    if isinstance(mgr, list) and mgr and isinstance(mgr[0], dict):
        m0 = mgr[0]
        info["manager"] = m0.get("name", "")
        info["manager_work_time"] = m0.get("workTime", "")
        fs = m0.get("fundSize", "")
        m = re.search(r"([\d.]+)\s*亿", str(fs))
        if m:
            info["scale_yi"] = float(m.group(1))
    if "scale_yi" not in info:
        scale_wan = detail.get("scale_wan")
        if isinstance(scale_wan, list) and scale_wan:
            info["scale_yi"] = round(
                float(scale_wan[-1].get("y", 0)) / 1e4, 2)  # 万元->亿
    # equity ratio from asset_alloc.series[0].data (last value)
    aa = detail.get("asset_alloc")
    if isinstance(aa, dict):
        series = (aa.get("series") or []) if isinstance(aa.get("series"), list) else []
        if series:
            s0 = series[0]
            data = s0.get("data") or []
            if data:
                info["equity_ratio"] = float(data[-1])
    return info


# ============================================================
#  VALUATION PERCENTILE (NAV-history based, Phase C fallback)
# ============================================================

def nav_based_valuation_percentile(nav_history: List) -> Optional[float]:
    """Estimate a 0-100 valuation percentile from a fund's own cumulative NAV.

    Method: for cumulative NAV (netWorthTrend), compute where the latest value
    sits within its own multi-year range. Banded interpretation:
      low = cheap (deep below historical high), high = expensive (near all-time high).

    Note: this is a *weak* proxy when no external PE/PB is available. It is only
    used as the valuation factor source for funds where index-sector mapping is
    unavailable. Validated against real PE when index estimate exists.
    """
    closes = []
    for pt in nav_history or []:
        c = pt.get("y") if isinstance(pt, dict) else pt
        if isinstance(c, (int, float)):
            closes.append(float(c))
    if len(closes) < 60:
        return None
    cur = closes[-1]
    lo = min(closes)
    hi = max(closes)
    if hi <= lo:
        return None
    # position 0..1 within range; invert so low price => low percentile (cheap)
    raw_pos = (cur - lo) / (hi - lo)
    return round(max(0.0, min(100.0, raw_pos * 100.0)), 1)


# ============================================================
#  PEER / MARKET BENCHMARK (RFC-006 方案D)
# ============================================================

def compute_peer_benchmark(
    qi,
    index_points: List[Tuple[str, float]],
    market_name: str = "沪深300",
) -> Optional:
    """Fill qi.peer_benchmark with market context from an index close series.

    Used so the fact card can say "本基金波动 42% vs 大盘 18% (2.3x 远高于)"
    instead of leaving an isolated number with no reference.

    Returns the PeerBenchmarkData (and attaches it to qi). Pure math, no LLM.
    """
    from .models import PeerBenchmarkData
    if not index_points or qi is None or qi.nav_history_days < 30:
        return None

    closes = [c for _, c in index_points]
    if len(closes) < 30:
        return None
    import numpy as np
    arr = np.asarray(closes, dtype=float)
    rets = np.diff(arr) / arr[:-1]

    market_vol = float(np.std(rets) * np.sqrt(252) * 100)
    market_6m = float((arr[-1] / arr[-126] - 1) * 100) if len(arr) >= 126 else None
    market_1y = float((arr[-1] / arr[-244] - 1) * 100) if len(arr) >= 244 else None
    market_dd = float((arr[-1] / np.max(arr) - 1) * 100)

    pb = PeerBenchmarkData(
        market_name=market_name,
        market_annual_volatility=round(market_vol, 2),
        market_return_6m=round(market_6m, 2) if market_6m is not None else None,
        market_return_1y=round(market_1y, 2) if market_1y is not None else None,
        market_current_drawdown=round(market_dd, 2),
    )

    fund_vol = qi.risk.annual_volatility_pct if qi.risk else None
    fund_6m = qi.returns.return_6m_pct if qi.returns else None
    if fund_vol:
        pb.vol_ratio = round(fund_vol / market_vol if market_vol else 0.0, 2)
    if fund_6m is not None and market_6m is not None:
        pb.excess_6m = round(fund_6m - market_6m, 2)

    qi.peer_benchmark = pb
    return pb


# ============================================================
#  BATCH FETCH
# ============================================================

async def batch_fetch_indexes(client, names: Optional[List[str]] = None,
                              limit: int = 500) -> Dict[str, List[Tuple[str, float]]]:
    """Fetch several indexes concurrently."""
    names = names or list(INDEXES.keys())
    out = {}
    for name in names:
        pts = await fetch_index_nav(client, name, limit=limit)
        if pts:
            out[name] = pts
    return out

"""index_bindings.py — 基金↔指数映射 + 基准指数抓取 (RFC-020 块5 基准对比)。

用途:
  1. 基准对比: 组合整体以沪深300为市场基准, 供 compute_peer_benchmark 使用
     (让报告能说"本基金波动 vs 大盘、超额收益")。
  2. 每只基金对应一个行业/宽基指数 (供短线择时 intraday 使用)。

数据源: 腾讯行情 (ifzq.gtimg.cn 历史K线)。
调研结论(2026-08-03): eastmoney push2his/httpx 被 TLS 指纹拦截(封死);
腾讯 gtimg.cn 对 httpx 完全开放且稳定, 故统一用腾讯。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# 组合市场基准
BENCHMARK_INDEX = "沪深300"

# 指数 → 腾讯历史K线代码
INDEX_QTCODE = {
    "沪深300": "sh000300",
    "中证白酒": "sz399997",
    "科创50": "sh000688",
    "纳斯达克100": "usNDX",
}

# 基金代码 → 跟踪/近似指数 (短线择时/行业对比; 未配置则跳过, 不报错)
FUND_INDEX_MAP = {
    "161725": "中证白酒",     # 招商中证白酒
    "000311": "沪深300",     # 景顺长城沪深300增强
    "588760": "科创50",      # 科创综指ETF
    "018044": "纳斯达克100",  # 天弘纳指QDII
}

_QT_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/fqkline/get"
_TIMEOUT = httpx.Timeout(12.0)
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}


def fetch_benchmark_points(
    index_name: str = BENCHMARK_INDEX,
    limit: int = 500,
) -> Optional[List[Tuple[str, float]]]:
    """抓指数日K收盘序列 [(date, close), ...] 旧→新(腾讯源)。失败返回 None(不抛)。"""
    qcode = INDEX_QTCODE.get(index_name)
    if not qcode:
        logger.warning("unknown benchmark index %s", index_name)
        return None
    try:
        params = {"param": f"{qcode},day,,,{max(limit, 320)},qfq"}
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, http2=False) as c:
            resp = c.get(_QT_KLINE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        node = (data.get("data") or {}).get(qcode) or {}
        klines = node.get("day") or node.get("qfqday") or []
        points = []
        for k in klines:
            if isinstance(k, (list, tuple)) and len(k) >= 3:
                points.append((str(k[0]), float(k[2])))  # date, close
        return points[-limit:] if points else None
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_benchmark_points failed for %s: %s", index_name, e)
        return None

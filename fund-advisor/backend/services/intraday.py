"""intraday.py — 盘中短线(择时)信号 (RFC-020 块3)。

用户确认: 取消轮询, 仅在 14:00 分析时拉一次行情数据即可。
只产 execution_advice(今日执行/观望/加急), 绝不改 target_weight/action_amount。

数据源: 腾讯行情 (qt.gtimg.cn 实时 + ifzq.gtimg.cn 历史K线)。
调研结论(2026-08-03): eastmoney 对 Python httpx 做 TLS 指纹拦截(封死);
腾讯 gtimg.cn 对 httpx 完全开放(实测 200), 且覆盖 A股指数+美股纳指, 故以此为准。
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

# 基金代码 → 跟踪指数
FUND_INTRADAY_INDEX = {
    "161725": "中证白酒",
    "000311": "沪深300",
    "588760": "科创50",
    "018044": "纳斯达克100",
    "270042": "纳斯达克100",
    "022430": "中证A500",
    "013308": "恒生科技",
}

# 指数 → 腾讯代码
INDEX_QTCODE = {
    "沪深300": "sh000300",
    "中证白酒": "sz399997",
    "科创50": "sh000688",
    "纳斯达克100": "usNDX",
    "中证A500": "sh000510",
    "恒生科技": "hkHSTECH",
}

# 指数交易市场。14:00 时 A 股和港股通常处于盘中；美股尚未开盘，
# 纳指数据只能代表最近一个美股交易时段，不能冒充当日基金实时净值。
INDEX_MARKET = {
    "沪深300": "CN",
    "中证白酒": "CN",
    "科创50": "CN",
    "纳斯达克100": "US",
    "中证A500": "CN",
    "恒生科技": "HK",
}

_QT_REALTIME_URL = "https://qt.gtimg.cn/q="
_QT_KLINE_URL = "https://ifzq.gtimg.cn/appstock/app/fqkline/get"
_TIMEOUT = httpx.Timeout(12.0)
_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
# 短线择时阈值: 2% 明显, 1% 轻微
_OVERSOLD = -2.0
_OVERBOUGHT = 2.0
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, http2=False)


def fetch_intraday(index_name: str) -> Optional[dict]:
    """腾讯实时快照。返回 {index, price, prev_close, pct_today, high, low}, 失败 None。"""
    qcode = INDEX_QTCODE.get(index_name)
    if not qcode:
        logger.warning("no qtcode for %s", index_name)
        return None
    try:
        with _client() as c:
            resp = c.get(_QT_REALTIME_URL + qcode)
            resp.raise_for_status()
            # 响应是 GBK 编码的 v_xxx="..."; 按 ~ 分列
            text = resp.content.decode("gbk", errors="ignore")
            body = text.split("=", 1)[-1].strip().strip('"')
            fld = body.split("~")
        if len(fld) < 35:
            return None
        try:
            price = float(fld[3])
            prev_close = float(fld[4])
            pct = float(fld[32])
            high = float(fld[33]) if len(fld) > 33 else None
            low = float(fld[34]) if len(fld) > 34 else None
        except (ValueError, IndexError):
            return None
        return {
            "index": index_name,
            "price": price,
            "prev_close": prev_close,
            "pct_today": round(pct, 2),
            "high": high,
            "low": low,
            "quote_time": fld[30] if len(fld) > 30 and fld[30] else None,
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("intraday fetch %s failed: %s", index_name, e)
        return None


def fetch_history(index_name: str, days: int = 30) -> Optional[List[Tuple[str, float]]]:
    """腾讯历史日K收盘 [(date, close), ...] 旧→新。失败 None。"""
    qcode = INDEX_QTCODE.get(index_name)
    if not qcode:
        return None
    try:
        params = {"param": f"{qcode},day,,,{days},qfq"}
        with _client() as c:
            resp = c.get(_QT_KLINE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        node = (data.get("data") or {}).get(qcode) or {}
        klines = node.get("day") or node.get("qfqday") or []
        out = []
        for k in klines:
            if isinstance(k, (list, tuple)) and len(k) >= 3:
                out.append((str(k[0]), float(k[2])))  # date, close
        return out or None
    except Exception as e:  # noqa: BLE001
        logger.debug("intraday history %s failed: %s", index_name, e)
        return None


def intraday_signal(pct_today: Optional[float], close_vs_ma5: Optional[float] = None) -> dict:
    """由"今日实时涨跌% + 现价相对5日线偏离%"得短线信号。

    close_vs_ma5: 正=现价在5日线上方(偏贵), 负=下方(偏便宜)。
    """
    raw_pct = pct_today
    if raw_pct is None:
        return {
            "signal": "neutral", "execution_advice": "观望",
            "pct_today": None, "vs_ma5": close_vs_ma5,
            "note": "实时数据不可用, 短线不参与(仅长期+自适应)",
        }
    # 叠加判断: 今日跌 + 现价在5日线下方 → 双重超跌, 较佳买点
    adv = "中性"
    signal = "neutral"
    if raw_pct <= _OVERSOLD:
        if close_vs_ma5 is not None and close_vs_ma5 < 0:
            adv, signal = "较佳买点", "oversold"
        else:
            adv, signal = "偏买点", "oversold"
    elif raw_pct >= _OVERBOUGHT:
        if close_vs_ma5 is not None and close_vs_ma5 > 0:
            adv, signal = "加急" if False else "偏高观察", "overbought"
        else:
            adv, signal = "偏高观察", "overbought"
    elif raw_pct <= -1.0:
        adv = "偏买点" if (close_vs_ma5 is None or close_vs_ma5 < 0) else "中性"
    elif raw_pct >= 1.0:
        adv = "偏高观察"
    return {
        "signal": signal, "execution_advice": adv,
        "pct_today": round(raw_pct, 2),
        "vs_ma5": round(close_vs_ma5, 2) if close_vs_ma5 is not None else None,
        "note": "",
    }


def market_quote_context(index_name: str, now: Optional[datetime] = None) -> dict:
    """说明行情在中国决策时点是否属于本市场实时盘中数据。"""
    current = now or datetime.now(_SHANGHAI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_SHANGHAI_TZ)
    else:
        current = current.astimezone(_SHANGHAI_TZ)

    market = INDEX_MARKET.get(index_name, "UNKNOWN")
    weekday = current.weekday() < 5
    clock = current.time().replace(tzinfo=None)
    if market == "CN":
        in_session = weekday and (
            time(9, 30) <= clock <= time(11, 30)
            or time(13, 0) <= clock <= time(15, 0)
        )
        semantics = "A股指数盘中方向" if in_session else "A股最近行情；当前非连续交易时段"
    elif market == "HK":
        in_session = weekday and (
            time(9, 30) <= clock <= time(12, 0)
            or time(13, 0) <= clock <= time(16, 0)
        )
        semantics = "港股指数盘中方向" if in_session else "港股最近行情；当前非连续交易时段"
    elif market == "US":
        in_session = False
        semantics = (
            f"最近一个美股交易时段；中国{current:%H:%M}不代表今晚纳指走势或基金精确净值"
        )
    else:
        in_session = False
        semantics = "未知市场行情，仅作辅助参考"
    return {
        "market": market,
        "decision_live": in_session,
        "quote_semantics": semantics,
        "decision_time": f"{current:%H:%M} Asia/Shanghai",
        "holiday_calendar_checked": False,
    }


def build_intraday_view(fund_codes, now: Optional[datetime] = None) -> Dict[str, dict]:
    """为当前基金拉指数快照与5日线，并明确行情时效边界。"""
    out: Dict[str, dict] = {}
    for code in fund_codes:
        idx = FUND_INTRADAY_INDEX.get(code)
        if not idx:
            continue
        snap = fetch_intraday(idx)
        # 5日线偏离: 现价 vs 近5日收盘均值
        close_vs_ma5 = None
        if snap:
            hist = fetch_history(idx, days=5)
            if hist:
                closes = [c for _, c in hist]
                ma5 = sum(closes) / len(closes)
                close_vs_ma5 = (snap["price"] / ma5 - 1) * 100.0
        sig = intraday_signal(snap["pct_today"] if snap else None, close_vs_ma5)
        context = market_quote_context(idx, now=now)
        out[code] = {
            "index": idx,
            **sig,
            "realtime_ok": snap is not None,
            "source": "腾讯行情",
            "quote_time": snap.get("quote_time") if snap else None,
            **context,
        }
    return out

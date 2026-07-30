"""Facts Computer — 纯Python计算所有客观分析数据。

不依赖任何LLM，基于DB持仓和净值数据预计算，为LLM分析提供数据锚点。
确保每一条分析都引用具体数据，不能凭空推测。
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.fund import Fund
from backend.models.holding import FundHolding
from backend.models.portfolio_snapshot import PortfolioSnapshot
from backend.models.nav_history import FundNavHistory


def compute_portfolio_facts(db: Session) -> dict:
    """计算所有可量化的组合数据，不依赖LLM。

    返回的字典包含：
      - summary: 总览（市值、成本、盈亏、份额比例等）
      - per_fund: 每只基金的详细计算数据
      - concentration: 集中度分析
      - trend: 组合净值趋势快照
      - platform_split: 平台分布
    
    所有数字精确到2位小数，百分比为浮点。
    """

    money_fund_codes = _money_fund_codes(db)
    holdings = _load_holdings(db)

    # ---- 逐基金计算 ----
    per_fund = []
    total_mv = Decimal("0")
    total_cost = Decimal("0")

    for h, f in holdings:
        code = h.fund_code
        shares = h.shares or Decimal("0")
        is_money = code in money_fund_codes

        # 当前市值
        if is_money:
            mv = shares
        elif f and f.latest_nav and shares:
            mv = shares * f.latest_nav
        else:
            mv = h.market_value or Decimal("0")

        # 成本
        if h.cost_nav and shares:
            cost = shares * h.cost_nav
        else:
            cost = Decimal("0")

        # 单基金盈亏
        pnl = mv - cost
        pnl_pct = (float(pnl) / float(cost) * 100) if cost > 0 else 0.0

        # 成本净值 vs 当前净值
        latest_nav = float(f.latest_nav) if f and f.latest_nav else None
        cost_nav = float(h.cost_nav) if h.cost_nav else None
        nav_change = (latest_nav - cost_nav) if (latest_nav and cost_nav) else None
        nav_change_pct = ((latest_nav / cost_nav - 1) * 100) if (latest_nav and cost_nav and cost_nav > 0) else None

        # 基金类型
        fund_type = f.fund_type if f else "未知"

        total_mv += mv
        total_cost += cost

        per_fund.append({
            "fund_code": code,
            "fund_name": h.fund_name,
            "fund_type": fund_type,
            "platform": h.platform,
            "shares": round(float(shares), 4),
            "latest_nav": latest_nav,
            "cost_nav": cost_nav,
            "nav_change": round(nav_change, 4) if nav_change is not None else None,
            "nav_change_pct": round(nav_change_pct, 2) if nav_change_pct is not None else None,
            "current_mv": round(float(mv), 2),
            "cost_mv": round(float(cost), 2),
            "pnl": round(float(pnl), 2),
            "pnl_pct": round(pnl_pct, 2),
            "is_money_fund": is_money,
        })

    # ---- 总览 ----
    total_pnl = float(total_mv - total_cost)
    total_pnl_pct = (total_pnl / float(total_cost) * 100) if total_cost > 0 else 0.0

    # 各基金占比
    mv_map = {pf["fund_code"]: pf["current_mv"] for pf in per_fund}
    total_mv_float = float(total_mv)

    for pf in per_fund:
        pf["mv_ratio"] = round(pf["current_mv"] / total_mv_float * 100, 1) if total_mv_float > 0 else 0.0

    # ---- 集中度分析 ----
    ranked_by_mv = sorted(per_fund, key=lambda x: x["current_mv"], reverse=True)
    top3_mv = sum(p["current_mv"] for p in ranked_by_mv[:3])
    top3_ratio = round(top3_mv / total_mv_float * 100, 1) if total_mv_float > 0 else 0.0
    max_single = ranked_by_mv[0] if ranked_by_mv else None
    concentration = {
        "top3_ratio": top3_ratio,
        "top3_funds": [p["fund_code"] for p in ranked_by_mv[:3]],
        "max_single_ratio": round(max_single["current_mv"] / total_mv_float * 100, 1) if max_single and total_mv_float > 0 else 0.0,
        "max_single_fund": max_single["fund_code"] if max_single else "",
        "total_funds": len(per_fund),
    }

    # ---- 组合净值趋势 ----
    snapshots = _recent_snapshots(db, days=60)

    # ---- 平台分布 ----
    platform_map = {}
    for pf in per_fund:
        p = pf["platform"]
        platform_map.setdefault(p, {"mv": 0, "count": 0})
        platform_map[p]["mv"] += pf["current_mv"]
        platform_map[p]["count"] += 1
    platform_split = {
        plat: {
            "market_value": round(d["mv"], 2),
            "count": d["count"],
            "ratio": round(d["mv"] / total_mv_float * 100, 1) if total_mv_float > 0 else 0.0,
        }
        for plat, d in platform_map.items()
    }

    # ---- 趋势关键指标 ----
    trend_signals = _compute_trend_signals(snapshots)

    return {
        "summary": {
            "total_market_value": round(total_mv_float, 2),
            "total_cost": round(float(total_cost), 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "holding_count": len(per_fund),
            "last_portfolio_nav": snapshots[-1]["nav"] if snapshots else None,
        },
        "per_fund": per_fund,
        "concentration": concentration,
        "snapshots": snapshots,
        "platform_split": platform_split,
        "trend": trend_signals,
    }


# ---------------------------------------------------------------------------
# 内部方法
# ---------------------------------------------------------------------------

def _money_fund_codes(db: Session) -> set[str]:
    rows = db.execute(
        select(Fund.fund_code).where(Fund.fund_type == "货币型")
    ).scalars().all()
    return set(rows)


def _load_holdings(db: Session):
    rows = db.execute(
        select(FundHolding, Fund)
        .outerjoin(Fund, FundHolding.fund_code == Fund.fund_code)
        .where(FundHolding.status == 1)
    ).all()
    return rows


def _recent_snapshots(db: Session, days: int = 60) -> list[dict]:
    import datetime
    cutoff = datetime.date.today()
    rows = db.execute(
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


def _compute_trend_signals(snapshots: list[dict]) -> dict:
    """从组合净值趋势中提取关键信号（纯计算，不靠LLM）。
    所有返回字段都有默认值，调用方无需检查 KeyError。
    """
    defaults = {
        "state": "数据不足",
        "short_trend_pct": 0.0,
        "long_return_pct": 0.0,
        "volatility_pct": 0.0,
        "streak_days": 0,
        "streak_direction": "",
        "signals": [],
        "num_snapshots": len(snapshots) if snapshots else 0,
    }

    if not snapshots or len(snapshots) < 5:
        defaults["num_snapshots"] = len(snapshots) if snapshots else 0
        return defaults

    navs = [s["nav"] for s in snapshots if s.get("nav")]
    if len(navs) < 5:
        return defaults

    # 近期 vs 远期的移动平均
    short_nav = sum(navs[-5:]) / 5  # 近5天
    all_nav = sum(navs) / len(navs)  # 全周期
    early_nav = sum(navs[:10]) / min(10, len(navs))  # 早期10天
    last_nav = navs[-1]

    short_trend = (short_nav / all_nav - 1) * 100
    long_ret = (last_nav / early_nav - 1) * 100

    # 波动用标准差
    import math
    mean_nav = all_nav
    variance = sum((n - mean_nav) ** 2 for n in navs) / len(navs)
    volatility = math.sqrt(variance) / mean_nav * 100  # 变异系数

    # 连续涨跌
    streak = 0
    direction = ""
    if len(navs) >= 4:
        if navs[-1] > navs[-2]:
            direction = "连续上涨"
            for i in range(len(navs) - 2, -1, -1):
                if navs[i + 1] > navs[i]:
                    streak += 1
                else:
                    break
        elif navs[-1] < navs[-2]:
            direction = "连续下跌"
            for i in range(len(navs) - 2, -1, -1):
                if navs[i + 1] < navs[i]:
                    streak += 1
                else:
                    break

    # 综合判断
    if short_trend > 1.5:
        state = "近期强势(+{:.1f}%)".format(short_trend)
    elif short_trend > 0.5:
        state = "震荡偏强"
    elif short_trend > -0.5:
        state = "震荡"
    elif short_trend > -1.5:
        state = "震荡偏弱"
    else:
        state = "近期弱势({:.1f}%)".format(short_trend)

    signals = []
    if abs(short_trend) > 2:
        signals.append(f"近5日趋势变动显著({short_trend:+.1f}%)")
    if volatility > 3:
        signals.append(f"波动率偏高({volatility:.1f}%)")
    if streak >= 3:
        signals.append(f"{direction}{streak}日")
    if long_ret > 10:
        signals.append(f"近60日累计涨幅 {long_ret:.1f}%")
    elif long_ret < -10:
        signals.append(f"近60日累计跌幅 {long_ret:.1f}%")

    return {
        "state": state,
        "short_trend_pct": round(short_trend, 2),
        "long_return_pct": round(long_ret, 1),
        "volatility_pct": round(volatility, 1),
        "streak_days": streak,
        "streak_direction": direction,
        "signals": signals,
        "num_snapshots": len(navs),
    }

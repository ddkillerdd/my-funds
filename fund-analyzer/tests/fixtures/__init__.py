# FundAnalyzer test fixtures
# Centralized mock data generation

import random
import math
from typing import List

from engine.models import NavPoint, FundHolding


def make_nav_history(
    start_nav: float = 1.0,
    days: int = 120,
    drift: float = 0.0005,
    vol: float = 0.012,
    seed: int = 42,
) -> List[NavPoint]:
    """Generate simulated nav history."""
    random.seed(seed)
    nav = start_nav
    history = []
    for i in range(days):
        month = 3 + (i // 30)
        day = (i % 30) + 1
        if day > 28:
            day = 28
        date = f"2026-{month:02d}-{day:02d}"
        nav *= 1 + random.gauss(drift, vol)
        history.append(NavPoint(date=date, nav=round(nav, 6)))
    return history


def make_holding(
    code: str,
    name: str,
    fund_type: str = "股票型",
    start_nav: float = 1.0,
    drift: float = 0.0005,
    vol: float = 0.012,
    mv: float = 10000.0,
    cost: float = 9800.0,
    mv_ratio: float = 25.0,
    is_money: bool = False,
    days: int = 120,
    seed: int = 42,
) -> FundHolding:
    return FundHolding(
        fund_code=code,
        fund_name=name,
        fund_type=fund_type,
        current_mv=mv,
        cost=cost,
        mv_ratio=mv_ratio,
        is_money_fund=is_money,
        nav_history=make_nav_history(start_nav, days, drift, vol, seed),
    )


# Standard 4-fund test portfolio
def standard_portfolio() -> List[FundHolding]:
    return [
        make_holding("161725", "招商中证白酒指数C", drift=0.0008, vol=0.015, seed=1),
        make_holding("164906", "交银中证海外H3C", drift=0.0004, vol=0.012, seed=2),
        make_holding("000311", "景顺长城沪深300", drift=0.0005, vol=0.010, seed=3),
        make_holding("002758", "货币基金A", is_money=True, drift=0.0001, vol=0.001, seed=4),
    ]

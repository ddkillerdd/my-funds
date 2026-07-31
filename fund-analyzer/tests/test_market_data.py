"""Tests for the Market Data Layer (RFC-009 / Phase C)."""
from engine.market_data import (
    compute_peer_benchmark,
    extract_fund_info,
    nav_based_valuation_percentile,
)
from engine.models import FundHolding, NavPoint
from engine.quant import compute_all


def make_qi_from_navs(navs_float, code="161725", name="测试基金"):
    navs = [NavPoint(date="", nav=v) for v in navs_float]
    h = FundHolding(fund_code=code, fund_name=name, current_mv=10000,
                    cost=9000, nav_history=navs)
    return compute_all(h)


# ---------- extract_fund_info ----------

def test_extract_fund_info_scale_from_manager():
    detail = {
        "code": "161725",
        "fund_name": "招商中证白酒指数(LOF)A",
        "manager": [{"name": "侯昊", "workTime": "8年又345天",
                     "fundSize": "443.39亿(23只基金)"}],
        "asset_alloc": {"series": [{"name": "股票占净比", "data": [94.54, 94.79]}]},
    }
    info = extract_fund_info(detail)
    assert info["fund_name"] == "招商中证白酒指数(LOF)A"
    assert info["manager"] == "侯昊"
    assert info["scale_yi"] == 443.39
    assert info["equity_ratio"] == 94.79


def test_extract_fund_info_empty():
    assert extract_fund_info(None) == {}
    assert extract_fund_info({}) == {}


def test_extract_fund_info_scale_wan_fallback():
    detail = {"code": "x", "fund_name": "x",
              "scale_wan": [{"y": 250000}, {"y": 300000}]}
    info = extract_fund_info(detail)
    assert info["scale_yi"] == 30.0  # 300000万 -> 30亿


# ---------- valuation percentile ----------

def test_valuation_percentile_high_at_peak():
    # nav rising to a peak then staying there => percentile near top
    navs = [1.0 + i * 0.01 for i in range(100)]
    p = nav_based_valuation_percentile([{"y": v} for v in navs])
    assert p is not None and p > 80


def test_valuation_percentile_low_in_drawdown():
    # peak long ago, now near bottom => percentile low
    navs = [2.0 - (i / 100) * 1.5 for i in range(100)]  # falling from 2.0
    p = nav_based_valuation_percentile([{"y": max(v, 0.5)} for v in navs])
    assert p is not None and p < 30


def test_valuation_percentile_empty():
    assert nav_based_valuation_percentile([]) is None


# ---------- peer benchmark ----------

def test_compute_peer_benchmark_populates():
    # construct a fund with ~30+ days history
    fund_navs = [1.0 + i * 0.002 for i in range(300)]
    qi = make_qi_from_navs(fund_navs)
    # realistic index series with noise (not perfectly linear -> vol > 0)
    idx = []
    v = 3000.0
    import random
    rnd = random.Random(7)
    for i in range(300):
        v *= 1 + 0.0002 + rnd.gauss(0, 0.005)
        idx.append((str(i), v))
    pb = compute_peer_benchmark(qi, idx, market_name="沪深300")
    assert pb is not None
    assert pb.market_name == "沪深300"
    assert pb.market_annual_volatility is not None and pb.market_annual_volatility > 0
    assert qi.peer_benchmark is pb
    assert pb.vol_ratio is not None


def test_compute_peer_benchmark_short_index():
    fund_navs = [1.0 + i * 0.002 for i in range(120)]
    qi = make_qi_from_navs(fund_navs)
    pb = compute_peer_benchmark(qi, [(str(i), 3000.0) for i in range(5)],
                                market_name="沪深300")
    assert pb is None


def test_compute_peer_benchmark_excess_vs_market():
    # fund strongly outperforms a flat index => positive excess
    fund_navs = [1.0 + i * 0.01 for i in range(300)]
    qi = make_qi_from_navs(fund_navs)
    import random
    rnd = random.Random(8)
    idx = []
    v = 3000.0
    for i in range(300):
        v *= 1 + 0.0002 + rnd.gauss(0, 0.005)  # ~flat noisy index
        idx.append((str(i), v))
    pb = compute_peer_benchmark(qi, idx)
    assert pb is not None
    assert pb.excess_6m is not None and pb.excess_6m > 0

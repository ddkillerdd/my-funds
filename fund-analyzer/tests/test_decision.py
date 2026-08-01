"""Tests for engine.decision — RFC-013 动作确定性收敛 (B+R)."""

import pytest

from engine.models import QuantIndicators
from engine.decision import (
    score_views_quant,
    detect_regime,
    _series_trend,
    deterministic_action,
    merge_with_llm_explanation,
    summarize_regime,
)


def _make_qi(sharpe=1.5, vol=0.15, maxdd=15, trend_dir="up", macd="neutral",
             trend_strength=65, rsi=50):
    qi = QuantIndicators(
        fund_code="X", fund_name="X", fund_type="股票型",
        current_mv=0, cost=0, mv_ratio=0, pnl_amount=0, pnl_pct=0,
        is_money_fund=False, nav_history_days=250, data_quality="good",
    )
    qi.risk.annual_volatility_pct = vol
    qi.risk.max_drawdown_pct = -maxdd
    qi.risk.current_drawdown_pct = -maxdd * 0.4
    qi.efficiency.sharpe_ratio = sharpe
    qi.efficiency.sortino_ratio = sharpe * 0.8
    qi.trend.trend_direction = trend_dir
    qi.trend.trend_strength = trend_strength
    qi.trend.ma_status = "above_all" if trend_dir == "up" else "mixed"
    qi.macd.signal = macd
    qi.momentum.rsi_14 = rsi
    return qi


# ---------- Regime ----------

def test_series_trend_up():
    # 稳定上行序列
    up = [100 + i for i in range(60)]
    assert _series_trend(up) == "up"


def test_series_trend_down():
    down = [200 - i for i in range(60)]
    assert _series_trend(down) == "down"


def test_series_trend_sideways():
    flat = [100 + (i % 3) for i in range(60)]
    assert _series_trend(flat) == "sideways"


def test_detect_regime_bull():
    up = [100 + i for i in range(60)]
    ser = {"沪深300": up, "上证50": up, "创业板指": up, "中证500": up, "中证1000": up}
    assert detect_regime(ser) == "bull"


def test_detect_regime_bear():
    down = [200 - i for i in range(60)]
    ser = {"沪深300": down, "上证50": down, "创业板指": down, "中证500": down, "中证1000": down}
    assert detect_regime(ser) == "bear"


def test_detect_regime_sideways():
    flat = [100 + (i % 3) for i in range(60)]
    up = [100 + i for i in range(60)]
    ser = {"沪深300": flat, "上证50": up, "创业板指": flat, "中证500": flat, "中证1000": up}
    assert detect_regime(ser) == "sideways"


# ---------- 四视角分数 ----------

def test_score_views_quant_bounds_and_value():
    qi = _make_qi(sharpe=1.5, vol=0.15)
    vs = score_views_quant(qi)
    for k in ("trend", "risk", "value", "tech", "overall"):
        assert 0 <= vs[k] <= 100, f"{k}={vs[k]} 越界"
    # sharpe=1.5 → value=75
    assert vs["value"] == 75


def test_score_views_quant_idempotent():
    qi = _make_qi()
    assert score_views_quant(qi) == score_views_quant(qi)


# ---------- 六档动作 ----------

def test_action_sell_on_deep_drawdown():
    qi = _make_qi(sharpe=-1.0, maxdd=50)  # cur_dd 20 <30, 但 sharpe<-0.5
    a = deterministic_action("bear", qi)
    assert a["type"] == "reduce" or a["type"] == "sell"


def test_action_add_on_good_qi_bull():
    qi = _make_qi(sharpe=2.0, vol=0.10, trend_dir="up", trend_strength=80)
    a = deterministic_action("bull", qi)
    assert a["type"] == "increase"


def test_action_reduce_on_poor_sharpe_bear():
    qi = _make_qi(sharpe=-0.4, trend_dir="down", maxdd=20)
    a = deterministic_action("bear", qi)
    assert a["type"] == "reduce"


def test_action_hold_exemption_dd_released():
    # 回撤已释放 + 趋势向好 => 豁免减仓 → hold
    qi = _make_qi(sharpe=-0.2, maxdd=40, trend_dir="up")
    qi.risk.current_drawdown_pct = -5.0  # 远小于 max_dd 一半
    a = deterministic_action("sideways", qi)
    assert a["type"] == "hold"


def test_action_bull_lenient_keeps_good_asset():
    # 牛市模式下，sharpe 轻微负但趋势向上 → 豁免 → hold（不误减仓）
    qi = _make_qi(sharpe=-0.2, trend_dir="up", maxdd=30, trend_strength=70)
    qi.risk.current_drawdown_pct = -12.0
    a = deterministic_action("bull", qi)
    assert a["type"] == "hold"


def test_action_watch_on_death_cross():
    qi = _make_qi(sharpe=0.5, trend_dir="down", macd="death_cross_active")
    a = deterministic_action("sideways", qi)
    assert a["type"] in ("watch", "reduce", "hold")


# ---------- 幂等 ----------

def test_action_idempotent():
    qi = _make_qi(sharpe=1.2, trend_dir="up", trend_strength=75)
    a1 = deterministic_action("bull", qi)
    a2 = deterministic_action("bull", qi)
    assert a1 == a2


# ---------- 冲突合并 ----------

def test_merge_quant_wins_over_llm():
    qi = _make_qi(sharpe=-0.4, trend_dir="down")
    quant = deterministic_action("bear", qi)  # reduce
    # LLM 说 hold（与量化冲突）
    llm_debate = {"action": {"type": "hold", "reasoning": "我认为该持有"}}
    merged = merge_with_llm_explanation(quant, llm_debate)
    # 动作锁死为量化 reduce，LLM 观点变附注
    assert merged["type"] == quant["type"]
    assert "LLM 原判" in merged.get("note", "")
    assert "LLM解读" in merged.get("reasoning", "")


def test_merge_no_llm_keeps_quant():
    qi = _make_qi(sharpe=1.2, trend_dir="up")
    quant = deterministic_action("bull", qi)
    merged = merge_with_llm_explanation(quant, None)
    assert merged["type"] == quant["type"]
    assert "note" not in merged


# ---------- regime 汇总 ----------

def test_summarize_regime_bull():
    r = summarize_regime({"a": "bull", "b": "bull", "c": "bull", "d": "sideways"})
    assert r["regime"] == "bull"


def test_summarize_regime_mixed():
    r = summarize_regime({"a": "bull", "b": "bear"})
    assert r["regime"] == "sideways"

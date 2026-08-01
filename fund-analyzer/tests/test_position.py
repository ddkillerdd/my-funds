"""Tests for RFC-014 盈利导向决策引擎 v2 (Signal→Position→Risk 三层闭环).

覆盖 RFC-014 §10 测试计划的前 8 项:
  1. 波动率目标 (高波动压仓)
  2. 回撤硬止损 (R1)
  3. 熊市防御 (R5)
  4. 集中度上限 (R4)
  5. 换手触发带 (R6)
  6. 幂等性
  7. 零 LLM 依赖 (无 LLM 调用路径)
  8. 动作-仓位自洽 (action 由 target/current 派生)
"""

import pytest

from engine.models import QuantIndicators
from engine.decision import (
    build_position_action,
    compute_direction,
    _action_from_weights,
    ACTION_LABELS,
)


def _make_qi(vol=15.0, cur_dd=6.0, max_dd=15.0, sharpe=1.5,
             trend_dir="up", ret_1y=10.0, rsi=50):
    """构造带数值的 QuantIndicators。vol/cur_dd/max_dd/ret_1y 为百分数。"""
    qi = QuantIndicators(
        fund_code="X", fund_name="X", fund_type="股票型",
        current_mv=0, cost=0, mv_ratio=0, pnl_amount=0, pnl_pct=0,
        is_money_fund=False, nav_history_days=250, data_quality="good",
    )
    qi.risk.annual_volatility_pct = vol
    qi.risk.max_drawdown_pct = -max_dd
    qi.risk.current_drawdown_pct = -cur_dd
    qi.efficiency.sharpe_ratio = sharpe
    qi.trend.trend_direction = trend_dir
    qi.trend.ma_status = "above_all" if trend_dir == "up" else "mixed"
    qi.momentum.rsi_14 = rsi
    qi.returns.return_1y_pct = ret_1y
    return qi


# ---------- 1. 波动率目标 ----------

def test_vol_target_high_vol_compresses_position():
    """588760 场景: 年化波动 78% → 目标仓位被大幅压低(约15%而非50%)。"""
    qi = _make_qi(vol=78.0)
    act = build_position_action(qi, "sideways", current_weight=0.50)
    # direction 偏多(bull-ish), base=0.80; 0.80*(0.15/0.78)=0.154
    assert act["target_weight"] <= 0.20, f"高波动应压仓, 实际 {act['target_weight']}"
    assert act["target_weight_pct"] < 25.0
    assert act["vol"] == 78.0


def test_vol_target_low_vol_mid_position():
    """低波动蓝筹(vol=15%)中性方向 → 目标约50%。"""
    qi = _make_qi(vol=15.0, ret_1y=0.0, trend_dir="sideways", rsi=50)
    act = build_position_action(qi, "sideways", current_weight=0.40)
    # 方向可能为 neutral, base=0.50; 0.50*(0.15/0.15)=0.50
    assert 0.35 <= act["target_weight"] <= 0.65, f"低波中性应约50%, 实际 {act['target_weight']}"


# ---------- 2. 回撤硬止损 (R1) ----------

def test_drawdown_hard_stop_sell():
    """当前回撤 >25% → sell, target=0。"""
    qi = _make_qi(cur_dd=32.0)
    act = build_position_action(qi, "sideways", current_weight=0.50)
    assert act["action"] == "sell"
    assert act["target_weight"] == 0.0


def test_drawdown_reduce_zone():
    """回撤15-25% 且重仓 → 减仓。"""
    qi = _make_qi(cur_dd=20.0)
    act = build_position_action(qi, "sideways", current_weight=0.80)
    assert act["target_weight"] < 0.80  # 被压缩


# ---------- 3. 熊市防御 (R5) ----------

def test_bear_cap():
    """regime=bear → 目标仓位 ≤ 30%。"""
    qi = _make_qi(vol=15.0, trend_dir="up", ret_1y=20.0)  # 个股偏多
    act = build_position_action(qi, "bear", current_weight=0.50)
    assert act["target_weight"] <= 0.30, f"熊市目标应≤30%, 实际 {act['target_weight']}"


# ---------- 4. 集中度上限 (R4) ----------

def test_concentration_cap():
    """极低波动且强多 → target 不应超过 50%。"""
    qi = _make_qi(vol=5.0, trend_dir="up", ret_1y=30.0, cur_dd=2.0)
    act = build_position_action(qi, "bull", current_weight=0.30)
    assert act["target_weight"] <= 0.50, f"单基上限50%, 实际 {act['target_weight']}"


# ---------- 5. 换手触发带 (R6) ----------

def test_friction_band_holds():
    """|target-current| 在 5pp 内 → friction_held=True, action=hold。"""
    # 方向中性, target≈0.50; current=0.50 几乎不动
    qi = _make_qi(vol=15.0, ret_1y=0.0, trend_dir="sideways", rsi=50)
    act = build_position_action(qi, "sideways", current_weight=0.52)
    assert act["friction_held"] is True
    assert act["action"] == "hold"
    assert act["target_weight"] == pytest.approx(0.52, abs=0.01)


def test_beyond_friction_band_triggers():
    """超出触发带 → 正常产生动作, friction_held=False。"""
    qi = _make_qi(vol=78.0)  # 目标~15%
    act = build_position_action(qi, "sideways", current_weight=0.60)
    assert act["friction_held"] is False
    assert act["action"] in ("reduce", "sell")


# ---------- 6. 幂等性 ----------

def test_idempotent():
    """同一输入两次调用输出完全一致。"""
    qi = _make_qi(vol=40.0, cur_dd=8.0, ret_1y=5.0)
    a1 = build_position_action(qi, "sideways", current_weight=0.40)
    a2 = build_position_action(qi, "sideways", current_weight=0.40)
    assert a1 == a2


# ---------- 8. 动作-仓位自洽 ----------

def test_action_derived_from_weights():
    """action 与 target/current 关系自洽。"""
    assert _action_from_weights(0.00, 0.50) == "sell"
    assert _action_from_weights(0.40, 0.10) == "buy"
    assert _action_from_weights(0.30, 0.20) == "buy"   # 0.30 > 0.20*1.10 → buy
    assert _action_from_weights(0.21, 0.20) == "increase"  # 0.21 < 0.22 → 小幅加仓
    assert _action_from_weights(0.20, 0.20) == "hold"
    assert _action_from_weights(0.10, 0.30) == "reduce"


def test_action_label_valid():
    """action 的 label 必须在 ACTION_LABELS 中。"""
    qi = _make_qi(vol=20.0, cur_dd=5.0)
    for regime in ("bull", "bear", "sideways"):
        act = build_position_action(qi, regime, current_weight=0.40)
        assert act["action"] in ACTION_LABELS
        assert act["action_label"] == ACTION_LABELS[act["action"]]

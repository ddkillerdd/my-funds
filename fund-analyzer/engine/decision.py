"""Deterministic Action Decision Engine (RFC-013 B+R)

核心原则（贯彻项目准则 + FINSABER 实证）：
  LLM 只做解读不做评分，动作/择时数字全量化。
  - 四视角分数：纯量化映射（trend强度→分 / vol→risk分 / sharpe→value分 / RSI→tech分）
  - 市场状态：regime-aware 牛/熊/震荡判段（保护盈利，避免牛市误减仓、熊市死扛）
  - 动作：六档量化决策矩阵（RFC-006 fallback_debate 提升为主路径，叠加 regime）
  - LLM 输出降级为解释文案，动作字段锁死为量化结果

本模块零 LLM 依赖、纯函数、幂等（同一输入必得同一输出）。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 可接受动作别名
_BUY_LIKE = {"buy", "add", "increase"}
_REDUCE_LIKE = {"reduce", "sell"}
_HOLD_LIKE = {"hold"}
_WATCH_LIKE = {"watch"}


# ============================================================
#  1. 四视角确定性分数（LLM 不再打分）
# ============================================================

def score_views_quant(qi) -> Dict[str, int]:
    """纯量化计算四视角分数（0-100），幂等。

    复刻原 fallback_*_diagnosis 的确定性映射，供动作决策使用。
    返回: {"trend":.., "risk":.., "value":.., "tech":.., "overall":..}
    """
    # --- trend: 趋势强度（若缺失则用均线状态兜底）---
    trend_score = 50
    if qi.trend and qi.trend.trend_strength is not None:
        trend_score = int(qi.trend.trend_strength)
    elif qi.trend:
        ms = qi.trend.ma_status
        trend_score = {"above_all": 80, "above_short": 62, "mixed": 50,
                       "below_short": 38, "below_all": 20}.get(ms, 50)

    # --- risk: 年化波动率越低分越高（低风险 = 高分）---
    vol = qi.risk.annual_volatility_pct if qi.risk else None
    if vol is None:
        risk_score = 50
    else:
        risk_score = max(0, min(100, int(100 - vol * 2)))

    # --- value: Sharpe 越高分越高 ---
    sharpe = qi.efficiency.sharpe_ratio if qi.efficiency else None
    if sharpe is None:
        value_score = 50
    else:
        value_score = max(0, min(100, int(sharpe * 50)))

    # --- tech: RSI 中枢 50，超买/超卖适度降分 ---
    rsi = qi.momentum.rsi_14 if qi.momentum else None
    if rsi is None:
        tech_score = 50
    elif 40 <= rsi <= 60:
        tech_score = 65
    elif 30 <= rsi < 40 or 60 < rsi <= 70:
        tech_score = 45
    else:
        tech_score = 30

    overall = int((trend_score + risk_score + value_score + tech_score) / 4)
    return {
        "trend": trend_score,
        "risk": risk_score,
        "value": value_score,
        "tech": tech_score,
        "overall": overall,
    }


# ============================================================
#  2. Regime 判段（牛/熊/震荡）— FINSABER 盈利导向
# ============================================================

def _series_trend(close_list: List[float]) -> str:
    """对单条指数收盘序列判短趋势（up/down/sideways）。

    用 20 日均线 + 近5日斜率：
      - 现价 > MA20 且近5日上行 → up
      - 现价 < MA20 且近5日下行 → down
      - 其他 → sideways
    """
    if not close_list or len(close_list) < 21:
        return "sideways"
    closes = close_list[-60:]
    ma20 = sum(closes[-20:]) / 20.0
    cur = closes[-1]
    slope = cur - closes[-6] if len(closes) >= 6 else 0
    if cur > ma20 * 1.01 and slope > 0:
        return "up"
    if cur < ma20 * 0.99 and slope < 0:
        return "down"
    return "sideways"


def detect_regime(index_series: Dict[str, List[float]]) -> str:
    """判市场状态（牛/熊/震荡）。

    Args:
        index_series: {"沪深300": [close,...], ...} 各指数收盘序列（时间升序）

    Returns:
        "bull" | "bear" | "sideways"

    规则（盈利导向，FINSABER）：
      - 多数指数(≥60%) 趋势 up → bull
      - 多数指数(≥60%) 趋势 down → bear
      - 其余 → sideways
    """
    if not index_series:
        return "sideways"
    dirs = [_series_trend(v) for v in index_series.values() if v]
    if not dirs:
        return "sideways"
    up = dirs.count("up")
    down = dirs.count("down")
    total = len(dirs)
    if up >= total * 0.6:
        return "bull"
    if down >= total * 0.6:
        return "bear"
    return "sideways"


# ============================================================
#  3. Regime-Aware 六档动作决策（纯量化，幂等）
# ============================================================

def _quant_facts(qi) -> Dict[str, float]:
    """抽取量化硬事实。"""
    sharpe = qi.efficiency.sharpe_ratio if qi.efficiency and qi.efficiency.sharpe_ratio is not None else 0.0
    sortino = qi.efficiency.sortino_ratio if qi.efficiency and qi.efficiency.sortino_ratio is not None else 0.0
    vol = qi.risk.annual_volatility_pct if qi.risk and qi.risk.annual_volatility_pct is not None else 0.0
    max_dd = abs(qi.risk.max_drawdown_pct or 0) if qi.risk else 0.0
    cur_dd = abs(qi.risk.current_drawdown_pct or 0) if qi.risk else 0.0
    macd_signal = qi.macd.signal or "unknown" if qi.macd else "unknown"
    trend_dir = qi.trend.trend_direction or "unknown" if qi.trend else "unknown"
    return {
        "sharpe": sharpe, "sortino": sortino, "vol": vol,
        "max_dd": max_dd, "cur_dd": cur_dd,
        "macd": macd_signal, "trend_dir": trend_dir,
    }


def deterministic_action(regime: str, qi, view_scores: Optional[Dict[str, int]] = None) -> Dict:
    """Regime-aware 六档量化动作（RFC-006 矩阵 + 牛熊感知）。幂等。

    Args:
        regime: "bull"|"bear"|"sideways"（detect_regime 输出）
        qi: QuantIndicators
        view_scores: score_views_quant() 输出（可选，缺省自动算）

    Returns:
        action dict: {type, confidence, reasoning, change_pct, trigger_conditions,
                      target_ratio_pct, decision_source, regime}
    """
    vs = view_scores or score_views_quant(qi)
    f = _quant_facts(qi)
    avg = vs["overall"]

    sharpe, vol = f["sharpe"], f["vol"]
    max_dd, cur_dd = f["max_dd"], f["cur_dd"]
    macd, trend_dir = f["macd"], f["trend_dir"]

    # 风险三要素
    dd_released = max_dd > 0 and cur_dd < max_dd * 0.5
    trend_up = trend_dir == "up"
    trend_down = trend_dir == "down"
    sharp_drop = sharpe < -0.5
    overbought_risk = vol > 60
    golden_cross = macd == "golden_cross_active"
    death_cross = macd == "death_cross_active"

    conditions: List[str] = []

    # ---- Regime 叠加（盈利导向核心）----
    # bear 模式：深回撤/负sharpe 从严（止损保护本金）
    # bull 模式：好资产从严减仓豁免（避免牛市误减仓丢收益）
    bear_harsh = regime == "bear"
    bull_lenient = regime == "bull"

    # ---- 六档决策 ----
    if avg < 30 or cur_dd > 30 or sharp_drop:
        # 清仓线（bear 更激进，任何 regime 触发即 sell）
        action_type = "sell"
        change = -100 if bear_harsh else (-50 if cur_dd > 30 else -30)
        reasoning = f"健康分{avg}+回撤{cur_dd:.1f}%+Sharpe{sharpe:.2f}触发清仓线"
        conditions.append("净值跌破MA60 → 全部清仓")
        conditions.append(f"当前回撤超过{max_dd * 0.6:.0f}%历史深度 → 强制止损")

    elif avg < 55 or sharpe < 0:
        # 减仓 or 豁免hold（看是否"风险已释放+趋势向好"）
        # 牛/震荡模式才豁免持有（拿住好资产）；熊市从严，不豁免 → 直接减仓止损
        exempt_hold = (dd_released and (trend_up or golden_cross))
        if bear_harsh:
            exempt_hold = False  # 熊市不豁免，止损优先
        # bull 模式对轻微负 sharpe + 趋势向上更宽容
        if not exempt_hold and bull_lenient and sharpe >= -0.3 and trend_up and dd_released:
            exempt_hold = True
        if exempt_hold:
            action_type = "hold"
            change = 0
            reasoning = (f"回撤已释放({cur_dd:.1f}%)+趋势向好，Sharpe{sharpe:.2f}略低但风险可控，"
                         f"建议持有而非减仓" + ("（牛市模式，保留盈利仓位）" if bull_lenient else ""))
            conditions.append("MACD柱 < -0.005 → 转为reduce")
            conditions.append("Sharpe连续2月<0 且趋势转down → 再评估减仓")
        else:
            action_type = "reduce"
            change = -20 if bear_harsh else (-20 if sharpe < 0 else -10)
            reasoning = f"Sharpe{sharpe:.2f}偏低，减仓{abs(change)}%控制风险" + ("（熊市，止损优先）" if bear_harsh else "")
            conditions.append("MACD柱 < -0.005 → 追加减仓5%")
            conditions.append(f"当前回撤 > -{max_dd * 0.6:.0f}% → 转为sell")

    elif avg > 75 and sharpe > 1.0 and trend_up:
        # 增持（bull 更进取；overbought 观望）
        if overbought_risk:
            action_type = "hold"
            change = 0
            reasoning = f"健康分{avg}+Sharpe{sharpe:.2f}良好但波动率{vol:.0f}%偏高，暂观望"
            conditions.append("波动率回落到60%以下 → 可增持10%")
        else:
            action_type = "add"
            change = 10 if regime in ("bull", "sideways") else 5
            reasoning = f"健康分{avg}+Sharpe{sharpe:.2f}三优信号" + ("（牛市，进取增持）" if regime == "bull" else "，建议增持")
            conditions.append("Sharpe连续2月>1.5 → 再增持5%")

    elif death_cross or trend_down:
        action_type = "watch"
        change = 0
        reasoning = "趋势走弱/MACD死叉，暂持但需监控" + ("（熊市，警惕进一步下探）" if bear_harsh else "")
        conditions.append("MACD柱 > 0.005 且持续3日 → 转为hold")
        conditions.append("RSI < 30 → 触发减仓10%")

    else:
        action_type = "hold"
        change = 0
        reasoning = "信号混合，维持当前仓位"
        conditions.append("MACD柱 < -0.005 → 转为reduce")

    return {
        "type": _canonical(action_type),
        "confidence": _base_confidence(regime, action_type),
        "reasoning": reasoning,
        "change_pct": change,
        "trigger_conditions": conditions,
        "target_ratio_pct": None,
        "decision_source": "quant_primary",
        "regime": regime,
    }


def _canonical(t: str) -> str:
    """把 sell/reduce → reduce；buy/add/increase → increase；watch/hold 保留。"""
    if t in _REDUCE_LIKE:
        return "reduce"
    if t in _BUY_LIKE:
        return "increase"
    if t in _WATCH_LIKE:
        return "watch"
    return "hold"


def _base_confidence(regime: str, action_type: str) -> float:
    """量化动作的基准置信度（regime 明确时更高，可被 RFC-012 校准）。"""
    if action_type == "sell":
        return 0.85
    if regime == "bear" and action_type == "reduce":
        return 0.75
    if regime == "bull" and action_type == "add":
        return 0.70
    return 0.55


# ============================================================
#  4. LLM 文案合并（动作锁死为量化结果，LLM 只提供解释）
# ============================================================

def merge_with_llm_explanation(quant_action: Dict, llm_debate) -> Dict:
    """把量化动作与 LLM 解读合并。

    - 动作字段（type/change_pct）以量化结果为准，LLM 无法覆盖
    - LLM 原本的 action.type/reasoning 降级为附注 note（若与量化冲突）
    - 返回最终 action dict（写入报告）
    """
    merged = dict(quant_action)
    merged["decision_source"] = "quant_primary"

    if llm_debate is None:
        return merged

    llm_action = None
    if isinstance(llm_debate, dict):
        llm_action = llm_debate.get("action")
    else:
        llm_action = getattr(llm_debate, "action", None)

    llm_type = None
    llm_reasoning = ""
    if isinstance(llm_action, dict):
        llm_type = llm_action.get("type")
        llm_reasoning = llm_action.get("reasoning", "") or ""
    elif llm_action is not None:
        llm_type = getattr(llm_action, "type", None)
        llm_reasoning = getattr(llm_action, "reasoning", "") or ""

    # LLM 解释文案（若有）补充进 reasoning
    if llm_reasoning and llm_reasoning not in merged.get("reasoning", ""):
        merged["reasoning"] = f"{merged['reasoning']}｜LLM解读：{llm_reasoning}"

    # 冲突检测：LLM 方向与量化不一致 → 附注标注（不改变动作）
    if llm_type:
        llm_canon = _canonical(str(llm_type).lower())
        quant_canon = merged["type"]
        if llm_canon != quant_canon:
            merged["note"] = (f"LLM 原判 {llm_canon} 与量化决策 {quant_canon} 冲突，"
                              f"已按量化结果处理（防 LLM 随机摆荡）。")
    return merged


# ============================================================
#  报告顶层 regime 汇总
# ============================================================

def summarize_regime(regimes: Dict[str, str]) -> Dict:
    """汇总多只基金 regime（组合层次），供报告 market_analysis 使用。"""
    vals = list(regimes.values())
    if not vals:
        return {"regime": "sideways", "detail": "数据不足"}
    bulls = vals.count("bull")
    bears = vals.count("bear")
    if bulls >= len(vals) * 0.6:
        regime = "bull"
        label = "市场偏强（牛）"
    elif bears >= len(vals) * 0.6:
        regime = "bear"
        label = "市场偏弱（熊）"
    else:
        regime = "sideways"
        label = "市场震荡/分歧"
    return {"regime": regime, "label": label, "bull": bulls, "bear": bears, "total": len(vals)}

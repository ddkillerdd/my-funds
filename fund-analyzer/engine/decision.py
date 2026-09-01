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

from .action_mapping import canonical_decision_action

logger = logging.getLogger(__name__)

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
    return canonical_decision_action(t)


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
    """把量化动作与 LLM 解读合并（RFC-014 优先，兼容 RFC-006）。

    - 动作字段（action/target_weight）以量化 PositionAction 为准，LLM 无法覆盖
    - 兼容旧路由：若 quant_action 是 RFC-006 老 dict（type/reasoning），沿用旧合并
    - LLM 解读文案仅附加到 reason/reasoning，永不改动作字段
    - 冲突仅作 note 标注
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

    # RFC-014: 是否 PositionAction dict（含 target_weight）
    is_position = "action" in merged and "target_weight" in merged

    # LLM 解释文案补进 reason（PositionAction）或 reasoning（旧 dict）
    if llm_reasoning:
        field = "reason" if is_position else "reasoning"
        cur = merged.get(field, "") or ""
        if llm_reasoning not in cur:
            merged[field] = f"{cur}｜LLM解读：{llm_reasoning}"
            if not is_position:
                merged["reasoning"] = merged[field]

    # 冲突检测：LLM 方向与量化不一致 → 附注（不改变动作）
    if llm_type:
        if is_position:
            quant_action_v = merged.get("action")
            llm_canon = _canonical(str(llm_type).lower())
            # RFC-014 五档 vs 旧六档: 统一映射后比较
            q_norm = {"sell": "sell", "reduce": "reduce", "hold": "hold",
                      "watch": "hold", "buy": "add", "increase": "add"}.get(
                          quant_action_v, quant_action_v)
            l_norm = {"sell": "sell", "reduce": "reduce", "hold": "hold",
                      "watch": "hold", "buy": "add", "increase": "add"}.get(
                          llm_canon, llm_canon)
            if l_norm != q_norm:
                merged["note"] = (
                    f"LLM 原判 {llm_canon} 与量化决策 {quant_action_v} 冲突，"
                    f"已按量化结果处理（防 LLM 随机摆荡）。"
                )
        else:
            llm_canon = _canonical(str(llm_type).lower())
            quant_canon = merged.get("type")
            if quant_canon and llm_canon != quant_canon:
                merged["note"] = (
                    f"LLM 原判 {llm_canon} 与量化决策 {quant_canon} 冲突，"
                    f"已按量化结果处理（防 LLM 随机摆荡）。"
                )

    # RFC-014 PositionAction: 补全中文标签（若未设置）
    if is_position and not merged.get("action_label"):
        merged["action_label"] = ACTION_LABELS.get(merged.get("action"), "持有")

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


# ============================================================
#  RFC-014 盈利导向决策引擎 v2（Signal→Position→Risk 三层闭环）
#  ============================================================
#  - L1 方向信号（动量为主 + 均线 + RSI 修正）→ direction_score
#  - L2 仓位映射（波动率目标 vol targeting）→ 目标权重
#  - L3 风控层（回撤硬止损/波动上限/集中度/熊市防御/换手触发带）强制覆盖
#  - 唯一权威动作结构 PositionAction：全量化、幂等、零 LLM
#  - 旧的 deterministic_action 保留为数据不足时的内部兜底
#  ============================================================

# L2 波动率目标（默认 15%，可由 config 注入覆盖）
DEFAULT_TARGET_VOL = 0.15
# L3 风控阈值（默认）
DD_HARD_STOP = 25.0        # R1 回撤>25% 清仓
DD_REDUCE_LO = 15.0        # R2 回撤15-25% 减仓
VOL_HIGH_CAP = 60.0        # R3 年化vol>60% 压仓
CONC_CAP = 0.50            # R4 单基目标权重上限 50%
BEAR_CAP = 0.30            # R5 熊市防御上限 30%
FRICTION_BAND_PP = 5.0     # R6 换手触发带 5 个百分点
BASE_WEIGHT = {"bull-ish": 0.80, "neutral": 0.50, "bear-ish": 0.25}
ACTION_LABELS = {
    "buy": "买入", "increase": "加仓", "hold": "持有",
    "reduce": "减仓", "sell": "卖出",
}


def _f(qi, val):
    """安全取可能为 None 的数值，返回 float。"""
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_direction(qi, regime: str) -> float:
    """L1 方向信号 → direction_score ∈ [-1, +1]

    子信号加权（实证依据见 RFC-014 §3.1）：
      mom(0.50): 近1年收益, 有效(>0)才计正, 幅度限幅
      ma (0.30): MA20 vs MA60 黄金/死叉/纠缠
      rsi(0.20): RSI14 偏离 50（超买≥70、超卖≤30 修正）
    """
    # mom: 近1年收益 %（TSMOM 实证最强）
    ret_1y = _f(qi, qi.returns.return_1y_pct if qi.returns else None)
    mom = 0.0 if ret_1y == 0 else max(-1.0, min(1.0, ret_1y / 25.0))

    # ma: MA20 vs MA60
    ma_status = getattr(qi.trend, "ma_status", "unknown") if qi.trend else "unknown"
    ma_map = {"above_all": 1.0, "above_short": 0.5, "mixed": 0.0,
              "below_short": -0.5, "below_all": -1.0}
    ma = ma_map.get(ma_status, 0.0)

    # rsi: 偏离 50（超买降分防追高, 超卖适度看多反转）
    rsi = _f(qi, qi.momentum.rsi_14 if qi.momentum else None)
    if rsi == 0:
        rsi_w = 0.0
    elif rsi >= 70:
        rsi_w = -0.5   # 超买, 防追高
    elif rsi <= 30:
        rsi_w = 0.3    # 超卖, 均值回归看多（轻）
    elif 40 <= rsi <= 60:
        rsi_w = 0.0
    else:
        rsi_w = (rsi - 50) / 100.0  # 中性带外轻微方向

    score = 0.50 * mom + 0.30 * ma + 0.20 * rsi_w

    # 熊市 regime 压制方向（防御）：市场级转熊则方向整体下调
    if regime == "bear":
        score = score * 0.6 - 0.2
    elif regime == "bull":
        score = score * 1.1 + 0.1

    return max(-1.0, min(1.0, score))


def _action_from_weights(target: float, current: float) -> str:
    """由 target vs current 派生动作（目标是唯一因, 动作是果）。"""
    if target <= 1e-6:
        return "sell"
    if target > current * 1.10:
        return "buy"
    if target > current:
        return "increase"
    if target < current * 0.90:
        return "reduce"
    return "hold"


def build_position_action(qi, regime: str, current_weight: float,
                          target_vol: float = DEFAULT_TARGET_VOL,
                          friction_band_pp: float = FRICTION_BAND_PP,
                          total_mv: float = 0.0,
                          current_mv: float = 0.0) -> dict:
    """RFC-014 总入口：L1 方向 → L2 波动率目标仓位 → L3 风控 → 唯一动作结构。

    幂等、零 LLM 依赖。返回 dict（PositionAction.to_dict() 同构）。

    RFC-021: 拆分「现有持仓市值」与「金额基准」。
    - current_mv: 该基金现有持仓市值(元) → current_amount 直接用真实值
    - total_mv:   金额基准(目标盘子 scale)。组合级增量分配在 analyzer 分析完后由
                  allocation.allocate_incremental_capital 统一重算 target_amount,
                  避免单基金独立缩放过早污染绝对金额。

    Args:
        qi: QuantIndicators
        regime: "bull"|"bear"|"sideways"
        current_weight: 当前权重(十进制, 0~1)
        target_vol: 目标年化波动率(默认0.15)
        friction_band_pp: 换手触发带(百分点, 默认5)
        total_mv: 金额基准(元)。>0 时额外计算绝对操作金额 action_amount。
        current_mv: 该基金现有持仓市值(元)。>0 时 current_amount 用真实值。
    """
    # L1 方向
    direction = compute_direction(qi, regime)
    if direction > 0.25:
        bucket = "bull-ish"
    elif direction < -0.25:
        bucket = "bear-ish"
    else:
        bucket = "neutral"
    base = BASE_WEIGHT[bucket]

    # L2 波动率目标
    vol = _f(qi, qi.risk.annual_volatility_pct if qi.risk else None)
    if vol <= 1e-6:
        target = base          # 无波动率数据, 用基准仓位
        vol_fact = None
    else:
        target = base * (target_vol / (vol / 100.0))
        vol_fact = target_vol / (vol / 100.0)

    # 用 R5 判定需要 direction; 先统一 clamp 再走风控
    target = max(min(target, 0.95), 0.05) if target > 0 else 0.0

    # L3 风控
    limited = _apply_risk_layers_for_direction(qi, regime, target, current_weight, direction)

    # R6 换手触发带: |target-current| < band → 保持不动
    friction_held = False
    if abs((limited - current_weight) * 100) < friction_band_pp:
        limited = current_weight
        friction_held = True

    target = max(min(limited, 0.95), 0.0)
    action = _action_from_weights(target, current_weight)

    # 因 R6 保持不动且原方向要减仓时, 动作统一为 hold
    if friction_held:
        action = "hold"

    # 依据文字
    reasons = []
    risk_memo = {}
    r1_hit = limited == 0.0
    cur_dd = abs(_f(qi, qi.risk.current_drawdown_pct if qi.risk else None))
    if r1_hit:
        reasons.append(f"回撤{cur_dd:.0f}%超阈值清仓")
    elif vol_fact is not None:
        reasons.append(f"波动率目标{target_vol*100:.0f}%→仓位{target*100:.0f}%")
    if friction_held:
        reasons.append(f"距目标<{friction_band_pp:.0f}pp, 保持不动")

    # 绝对操作金额: current = 真实现有持仓; target 由组合级分配器在 analyzer 层统一重算
    target_amount = total_mv * target if total_mv > 0 else None
    change_amount = total_mv * (target - current_weight) if total_mv > 0 else None
    current_amount = target_amount * current_weight if total_mv > 0 else None
    if current_mv > 0:
        # RFC-021: current_amount 应反映该基金真实现有市值, 而非“基准×权重”
        current_amount = current_mv
        # 若已知现值和目标盘子, change_amount 直接按元: 目标持有额-现持有额
        if total_mv > 0:
            target_amount = total_mv * target
            change_amount = target_amount - current_amount

    return {
        "fund_code": qi.fund_code,
        "action": action,
        "action_label": ACTION_LABELS.get(action, "持有"),
        "current_weight": round(current_weight, 4),
        "target_weight": round(target, 4),
        "change_weight_pp": round((target - current_weight) * 100, 2),
        "target_weight_pct": round(target * 100, 1),
        # 绝对金额（元）, 组合级分配器最终精修
        "target_amount": round(target_amount, 2) if target_amount is not None else None,
        "current_amount": round(current_amount, 2) if current_amount is not None else None,
        "action_amount": round(change_amount, 2) if change_amount is not None else None,
        "regime": regime,
        "direction_score": round(direction, 3),
        "momentum_12m": round(_f(qi, qi.returns.return_1y_pct if qi.returns else None), 2),
        "vol": round(vol, 1),
        "max_drawdown": round(-abs(_f(qi, qi.risk.max_drawdown_pct if qi.risk else None)), 1),
        "current_drawdown": round(-cur_dd, 1),
        "sharpe": round(_f(qi, qi.efficiency.sharpe_ratio if qi.efficiency else None), 2),
        "decision_source": "quant_primary",
        "reason": "".join(reasons) if reasons else "信号中性, 维持当前仓位",
        "risk_hits": [],
        "friction_held": friction_held,
    }


def _apply_risk_layers_for_direction(qi, regime, target, current_weight, direction):
    """L3 风控层执行（R1..R5），返回修正后 target。"""
    hits: List[str] = []
    cur_dd = abs(_f(qi, qi.risk.current_drawdown_pct if qi.risk else None))
    vol = _f(qi, qi.risk.annual_volatility_pct if qi.risk else None)

    # R1
    if cur_dd > DD_HARD_STOP:
        return 0.0
    # R2
    if DD_REDUCE_LO < cur_dd <= DD_HARD_STOP and current_weight > target * 1.5:
        target = target * 0.5
    # R3
    if vol > VOL_HIGH_CAP:
        target = min(target, 0.30)
    # R4
    if target > CONC_CAP:
        target = CONC_CAP
    # R5
    if regime == "bear":
        target = min(target, BEAR_CAP)
    return max(0.0, target)

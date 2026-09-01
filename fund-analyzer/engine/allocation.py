"""增量资金分配器 (RFC-021)

背景 / 缺陷修复
==============
旧逻辑把「用户可用操作资金」(available_capital) 误当作「组合总市值」作为
绝对金额定价基数 (total_capital → total_mv)，导致:
    - current_amount = 可用资金 × 当前权重   ❌ (应 = 现有持仓市值)
    - target_amount  = 可用资金 × 目标权重   ❌ (例: 10×47.7% = 5 元, 与 1.49 持仓对不上)

本模块将两个概念彻底拆分:
    - current_mv_i       : 基金 i 现有持仓市值 (真实)
    - available_capital  : 用户本次愿意投入的增量资金 (子弹)
    - total_scale        : 目标盘子 = Σ current_mv + available_capital

分配方法 (调研支撑:「能盈利」的稳健做法)
======================================
不采用纯「预测收益排名」(MVO/最大化收益) —— 对基金低信噪数据, 收益估计误差会
导致灾难性集中 (单个输入错就全域错位)。业界共识 (Investresolve/QuantInsti/CAIA):
    - 风险平价 / ERC / 逆波动率: 稳健, Sharpe 稳定, 不靠预测收益  ✅ 主选
    - MVO / 最大收益:          对输入误差极度敏感, 仅作参考        ⚠️

本项目已有的 target_weight (由「方向信号 + 波动率目标 target_vol」算出) 本身
已内含风险调整。因此增量资金的最优分配 = **把组合拉向每个基金的 target_weight**
(风险调整后的理想配比), 而非凭空预测收益。

算法
====
    T = Σ current_mv + available_capital
    对每只基金 i:
        ideal_i   = T × target_weight_i          # 目标持有金额
        add_i     = ideal_i − current_mv_i        # >0 需加仓 / <0 需减仓
    若 Σ max(add_i,0) ≤ available_capital:
        → 全部满足 (减仓基金释放现金回笼)
    否则:
        → 可用资金不足, 按 ideal_i(风险调整后) 比例压缩正加仓部分
    输出:
        target_amount_i = ideal_i (压缩后)
        action_amount_i = add_i   (压缩后, >0 加 / <0 减)
        allocated_capital = Σ 正加仓 (≤ available_capital)
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional


# 把单基金目标显式协调到整个组合的 100% 预算内。
def fit_target_weights_to_budget(
    *,
    current_weight: Dict[str, float],
    target_weight: Dict[str, float],
    codes: List[str],
) -> Dict[str, float]:
    """组合层协调超配目标，优先保留减仓结果并压缩新增仓位。

    该函数是策略层的显式预算协调；底层分配器仍会拒绝未经协调的超配输入。
    缺失目标按当前权重处理，显式零目标仍保持为零。
    """
    current = {code: float(current_weight.get(code, 0.0) or 0.0) for code in codes}
    desired: Dict[str, float] = {}
    for code in codes:
        raw = target_weight[code] if code in target_weight else current[code]
        try:
            weight = float(raw or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"基金 {code} 的目标权重不是有效数字: {raw!r}") from exc
        if not math.isfinite(weight) or weight < -1e-9 or weight > 1.0 + 1e-9:
            raise ValueError(f"基金 {code} 的目标权重必须在 0 到 1 之间: {weight!r}")
        desired[code] = min(1.0, max(0.0, weight))

    current_sum = sum(current.values())
    if current_sum > 1.0 + 1e-9:
        raise ValueError(f"当前组合权重合计超过100%: {current_sum:.6f}")
    if sum(desired.values()) <= 1.0 + 1e-9:
        return desired

    # 当前现金、减仓释放的仓位共同构成可用于新增仓位的预算。
    released = sum(max(current[code] - desired[code], 0.0) for code in codes)
    increase = sum(max(desired[code] - current[code], 0.0) for code in codes)
    budget = max(0.0, 1.0 - current_sum) + released
    scale = min(1.0, budget / increase) if increase > 0 else 0.0
    fitted = {
        code: (
            current[code] + (desired[code] - current[code]) * scale
            if desired[code] > current[code]
            else desired[code]
        )
        for code in codes
    }
    return fitted


def allocate_incremental_capital(
    *,
    current_mv: Dict[str, float],
    target_weight: Dict[str, float],
    available_capital: float,
    current_weight: Optional[Dict[str, float]] = None,
) -> Dict:
    """组合级增量资金分配。

    Args:
        current_mv:      {fund_code: 现有持仓市值(元)}
        target_weight:   {fund_code: 目标权重(十进制 0~1)}, 已由方向+波动率目标算出
        available_capital: 用户本次可用增量资金(元)  [None/<=0 时退化为纯持仓口径]
        current_weight:  {fund_code: 当前权重} (可选, 目标缺失时维持现有金额)

    Returns:
        {
            "total_scale": float,               目标盘子(元)
            "allocated_capital": float,         实际分配的增量(元) ≤ available
            "per_fund": {
                code: {
                    "current_mv": float,         现有持仓
                    "ideal_amount": float,       目标持有金额
                    "target_amount": float,      最终目标持有金额(压缩后)
                    "action_amount": float,      操作金额(>0 加 / <0 减)
                    "allocated_add": float,      分配的增量(仅正加仓部分)
                    "target_weight": float,      目标权重
                }
            },
            "fully_allocated": bool,             增量是否足额分配
            "notes": List[str],
        }
    """
    if not current_mv:
        return {
            "total_scale": 0.0,
            "allocated_capital": 0.0,
            "per_fund": {},
            "fully_allocated": True,
            "notes": ["无持仓"],
        }

    available = float(available_capital) if available_capital and available_capital > 0 else 0.0
    current_mv = {k: float(v or 0) for k, v in current_mv.items()}
    cur_sum = sum(current_mv.values())
    total_scale = cur_sum + available

    notes: List[str] = []
    if available > 0:
        notes.append(f"目标盘子{total_scale:.2f}元 = 现有持仓{cur_sum:.2f}元 + 可用增量资金{available:.2f}元")
    else:
        notes.append(f"目标盘子{total_scale:.2f}元 = 现有持仓{cur_sum:.2f}元 (未设置可用增量资金)")

    # 复制并校验权重，避免修改调用方传入的字典。
    codes = list(current_mv.keys())
    safe_target_weight: Dict[str, float] = {}
    for c in codes:
        # 显式传入的 0 表示清仓；完全缺失时才参考当前权重。
        raw_weight = target_weight[c] if c in target_weight else (
            current_weight.get(c, 0.0) if current_weight else 0.0
        )
        try:
            tw = float(raw_weight or 0.0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"基金 {c} 的目标权重不是有效数字: {raw_weight!r}") from exc
        if not math.isfinite(tw) or tw < -1e-9 or tw > 1.0 + 1e-9:
            raise ValueError(f"基金 {c} 的目标权重必须在 0 到 1 之间: {tw!r}")
        safe_target_weight[c] = min(1.0, max(0.0, tw))

    tw_sum = sum(safe_target_weight.values())
    if tw_sum > 1.0 + 1e-9:
        # 超配属于上游组合决策错误，不能在执行层静默改写策略目标。
        raise ValueError(f"目标权重合计超过100%: {tw_sum:.6f}")
    if tw_sum <= 1e-9:
        # 明确的全零目标表示全部转为现金/清仓，不能退化为等权。
        safe_target_weight = {c: 0.0 for c in codes}
        notes.append("无有效目标权重, 按全部现金/清仓处理")

    ideal: Dict[str, float] = {}
    add: Dict[str, float] = {}
    for c in codes:
        tw = safe_target_weight.get(c, 0.0)
        ideal[c] = total_scale * tw
        add[c] = ideal[c] - current_mv[c]      # >0 加仓 / <0 减仓

    # 汇总需加仓部分；已确认的减仓金额可以作为轮换资金来源。
    needed = sum(max(add[c], 0.0) for c in codes)
    released = sum(max(-add[c], 0.0) for c in codes)
    available_funding = available + released
    scale = 1.0
    fully = True
    if needed > available_funding + 1e-9:
        scale = available_funding / needed if available_funding > 0 else 0.0
        fully = False
        notes.append(
            f"资金不足: 理想加仓{needed:.2f}元 > 可用资金及已释放资金"
            f"{available_funding:.2f}元, 按{scale*100:.0f}%压缩"
        )
    elif released > 0:
        notes.append(f"减仓可释放资金{released:.2f}元, 纳入轮换资金计算")

    # 最终金额
    per_fund: Dict[str, dict] = {}
    scaled_adds: List[float] = []
    for c in codes:
        add_scaled = add[c] * scale if add[c] > 0 else add[c]   # 只压缩正加仓
        scaled_adds.append(add_scaled)
        target_amt = current_mv[c] + add_scaled
        per_fund[c] = {
            "current_mv": round(current_mv[c], 2),
            "ideal_amount": round(ideal[c], 2),
            "target_amount": round(target_amt, 2),
            "action_amount": round(add_scaled, 2),
            "allocated_add": round(add_scaled, 2) if add_scaled > 0 else 0.0,
            "target_weight": round(safe_target_weight.get(c, 0.0), 4),
        }

    # allocated_capital 表示外部新增资金，不把基金轮换中的卖出回款重复计入。
    allocated = max(0.0, sum(scaled_adds))

    return {
        "total_scale": round(total_scale, 2),
        "allocated_capital": round(allocated, 2),
        "per_fund": per_fund,
        "fully_allocated": fully,
        "notes": notes,
    }

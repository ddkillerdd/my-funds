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

from typing import Dict, List, Optional


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
        current_weight:  {fund_code: 当前权重} (可选, 仅用于打印/展示)

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

    # 用 target_weight 计算理想持有金额
    codes = list(current_mv.keys())
    tw_sum = sum(target_weight.get(c, 0.0) for c in codes)
    if tw_sum <= 0:
        # 无目标权重(全部 hold/中性) → 退化为等权或维持现状
        for c in codes:
            target_weight[c] = 1.0 / len(codes) if len(codes) else 0.0
        notes.append("无有效目标权重, 退化为等权分配")

    ideal: Dict[str, float] = {}
    add: Dict[str, float] = {}
    for c in codes:
        tw = target_weight.get(c, 0.0)
        ideal[c] = total_scale * tw
        add[c] = ideal[c] - current_mv[c]      # >0 加仓 / <0 减仓

    # 汇总需加仓部分
    needed = sum(max(add[c], 0.0) for c in codes)
    scale = 1.0
    fully = True
    if available > 0 and needed > available:
        scale = available / needed
        fully = False
        notes.append(f"增量资金不足: 理想加仓{needed:.2f}元 > 可用{available:.2f}元, 按{scale*100:.0f}%压缩")

    # 最终金额
    per_fund: Dict[str, dict] = {}
    allocated = 0.0
    for c in codes:
        add_scaled = add[c] * scale if add[c] > 0 else add[c]   # 只压缩正加仓
        if add_scaled > 0:
            allocated += add_scaled
        target_amt = current_mv[c] + add_scaled
        per_fund[c] = {
            "current_mv": round(current_mv[c], 2),
            "ideal_amount": round(ideal[c], 2),
            "target_amount": round(target_amt, 2),
            "action_amount": round(add_scaled, 2),
            "allocated_add": round(add_scaled, 2) if add_scaled > 0 else 0.0,
            "target_weight": round(target_weight.get(c, 0.0), 4),
        }

    return {
        "total_scale": round(total_scale, 2),
        "allocated_capital": round(allocated, 2),
        "per_fund": per_fund,
        "fully_allocated": fully,
        "notes": notes,
    }

"""PlanAllocatorService - 智能配比 (RFC-018 ③).

给选中基金算配比%(权重), 融入用户风险偏好。
- 基线: 复用 screener 的 suggested_ratio_pct(打分分散微调)
- 风控约束:
  - 单只上限 25%, 下限 5%
  - 全部权重和 = 100%
  - 高风险类(商品/行业/高波动)按 risk_profile 归一缩放
  - risk_profile 是 UI 层偏好, 内部映射现有 playbook + 权重缩放, 不另造策略概念
"""

import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

MAX_WEIGHT = 25.0   # 单只上限 %
MIN_WEIGHT = 5.0    # 单只下限 %
RATIO_CAP = 25.0    # suggested_ratio_pct 本身上限

# risk_profile 对高波动/商品/行业类基金的权重缩放
_HIGH_RISK_TYPES = {"商品", "QDII", "行业"}
_RISK_PROFILE_SCALE = {
    "conservative": 0.5,
    "balanced": 1.0,
    "aggressive": 1.2,
}


class PlanAllocatorService:
    def __init__(self, db: Session):
        self.db = db

    def allocate(
        self,
        picks: List[dict],
        risk_profile: str = "balanced",
        base_ratio_key: str = "suggested_ratio_pct",
    ) -> dict:
        """给选中基金算配比权重。

        picks: [{"fund_code","fund_name","fund_type","suggested_ratio_pct",...}]
        返回: {"weights": {code: pct}, "items": [含权重明细], "sum": 100.0, "notes":[...]}
        """
        scale = _RISK_PROFILE_SCALE.get(risk_profile, 1.0)

        # 1. 基线权重(suggested_ratio_pct, 不足则等权)
        n = len(picks)
        raw: Dict[str, float] = {}
        for p in picks:
            code = p["fund_code"]
            base = p.get(base_ratio_key) or (100.0 / n if n else 0)
            base = min(float(base), RATIO_CAP)
            ftype = (p.get("fund_type") or "")
            # 高风险类按 risk_profile 缩放
            if any(h in ftype for h in _HIGH_RISK_TYPES):
                base *= scale
            raw[code] = base

        # 2. 归一化到 100%(z 分数
        total_raw = sum(raw.values())
        if total_raw <= 0:
            for code in raw:
                raw[code] = 100.0 / n
        else:
            for code in raw:
                raw[code] = raw[code] / total_raw * 100.0

        # 3. 应用单只上下限(迭代收敛)
        eff_max = MAX_WEIGHT if n * MAX_WEIGHT >= 100.0 else round(100.0 / n, 2)
        weights = self._apply_bounds(raw, n, min_w=MIN_WEIGHT, max_w=MAX_WEIGHT)

        # 4. 组装 items
        name_map = {p["fund_code"]: p for p in picks}
        items = []
        for code, wgt in weights.items():
            p = name_map.get(code, {})
            items.append({
                "fund_code": code,
                "fund_name": p.get("fund_name") or code,
                "fund_type": p.get("fund_type"),
                "weight_pct": round(wgt, 2),
                "budget_amount": None,  # 由上层按 total_budget 填
            })

        eff_max = round(100.0 / n, 2) if n and n * MAX_WEIGHT < 100.0 else MAX_WEIGHT
        notes = [f"单只上限 {eff_max}%, 下限 {MIN_WEIGHT}%"]
        if n and n * MAX_WEIGHT < 100.0:
            notes.append(f"基金数过少({n}只), 单只上限自动放宽至 {eff_max}% 以满足权重和=100%")
        notes.append(f"风险偏好 {risk_profile}(高风险类 x{scale})")

        return {
            "weights": {k: round(v, 2) for k, v in weights.items()},
            "items": items,
            "sum": round(sum(weights.values()), 2),
            "notes": notes,
        }

    # ─────────────────────────────────────────
    #  上下限迭代收敛(保持 sum≈100)
    # ─────────────────────────────────────────
    def _apply_bounds(self, raw: Dict[str, float], n: int,
                      min_w: float, max_w: float) -> Dict[str, float]:
        # 若 n<=0 或 n*min >100 无法满足, 直接归一
        if n <= 0:
            return {}
        if n * min_w > 100.0:
            min_w = 100.0 / n
        # 若 n*max <100(基金数太少, 均分突破上限), 放宽单只上限为 100/n,
        # 否则上限不可满足(如 3 只×25%=75%<100%), 会陷入裁剪-归一化死循环
        if n * max_w < 100.0:
            max_w = 100.0 / n

        weights = dict(raw)
        for _ in range(50):
            # 上限裁剪
            excess = sum(max(0.0, w - max_w) for w in weights.values())
            if excess > 0.001:
                clippable = [c for c, w in weights.items() if w > max_w]
                for c in clippable:
                    weights[c] = max_w
                # 把多出部分按比例分给未到上限的
                unclipped = [c for c, w in weights.items() if w < max_w]
                unclipped_sum = sum(weights[c] for c in unclipped)
                for c in unclipped:
                    if unclipped_sum > 0:
                        weights[c] += excess * weights[c] / unclipped_sum
            # 下限裁剪(只在下限之和不超过100时)
            if min_w * len(weights) <= 100.0:
                below = [c for c, w in weights.items() if w < min_w]
                if below:
                    deficit = sum(min_w - w for w in [weights[c] for c in below])
                    for c in below:
                        weights[c] = min_w
                    # 从其余那扣
                    above = [c for c, w in weights.items() if weights[c] > min_w and c not in below]
                    above_sum = sum(weights[c] for c in above)
                    for c in above:
                        if above_sum > 0:
                            weights[c] = max(min_w, weights[c] - deficit * weights[c] / above_sum)
            # 归一化
            total = sum(weights.values())
            if total > 0:
                for c in weights:
                    weights[c] = weights[c] / total * 100.0
            # 收敛判断
            diff = max(abs(w - max_w) if w > max_w else 0 for w in weights.values()) \
                + max(abs(min_w - w) if w < min_w and min_w * len(weights) <= 100.0 else 0
                      for w in weights.values())
            if diff < 1e-6:
                break
        return weights

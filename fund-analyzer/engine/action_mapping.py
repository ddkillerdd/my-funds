"""跨层建议动作映射。

统一量化决策、回测和后端持久化对历史动作别名的理解，避免同一动作在
不同层被判断成不同方向。
"""

from __future__ import annotations

from typing import Optional


# 兼容历史报告中的动作别名。
ACTION_ALIASES = {
    "add": "increase",
}

# 正向和负向动作分别用于调仓与回测命中判断。
INCREASE_ACTIONS = frozenset(("buy", "increase"))
REDUCE_ACTIONS = frozenset(("sell", "reduce", "decrease"))
NEUTRAL_ACTIONS = frozenset(("hold", "watch"))


def normalize_action_name(action: object) -> str:
    """规范化动作名称，保留方向信息并兼容历史别名。"""
    raw = str(action or "").strip().lower()
    return ACTION_ALIASES.get(raw, raw)


def action_direction(action: object) -> Optional[str]:
    """返回动作方向：positive、negative、neutral 或 None。"""
    normalized = normalize_action_name(action)
    if normalized in INCREASE_ACTIONS:
        return "positive"
    if normalized in REDUCE_ACTIONS:
        return "negative"
    if normalized in NEUTRAL_ACTIONS:
        return "neutral"
    return None


def canonical_decision_action(action: object) -> str:
    """将历史动作折叠为量化决策引擎使用的标准动作。"""
    normalized = normalize_action_name(action)
    if normalized in INCREASE_ACTIONS:
        return "increase"
    if normalized in REDUCE_ACTIONS:
        return "reduce"
    if normalized == "watch":
        return "watch"
    return "hold"

"""
strategy_config.py — 策略参数配置层（RFC-017 自适应 · 参数分离核心）

设计目的
--------
原本 `build_position_action` 的 target_vol / friction_band_pp 由 analyzer(每日报告)
和 simulator(模拟回测) 共用同一份默认值(decision.py 的 DEFAULT_TARGET_VOL 等)。
这带来一个问题: 若想让"模拟侧自适应"自由探索参数, 会连带影响"报告侧"实盘建议。

本模块把参数解耦成两层:
  - 报告侧(approved): 只接受通过风控校验、经用户确认的参数, 否则用保守默认。
  - 模拟侧(explored): 回测/WFA 自由探索, 不影响报告。

同时按"量化风险特征"把基金聚成 低/中/高波动 三类, 每类持有独立的
target_vol / friction 区间 与 回撤硬上限 —— 呼应甲方案"分类动态回撤"。

防过拟合原则
------------
- 只调 target_vol / friction_band_pp 两个"风险旋钮", 决策内核(build_position_action 公式)不动。
- 分类基于量化特征(波动率/回撤), 非手动贴板块标签。
- 未经验证/未经人工确认的参数永远不进入报告侧。

本模块为纯逻辑, 零依赖外部状态, 可被 fund-analyzer 与 fund-advisor 两侧 import。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

# ---------------------------------------------------------------------------
# 保守默认(全局兜底, 未批准任何自适应时使用)
# ---------------------------------------------------------------------------
DEFAULT_TARGET_VOL = 0.15
DEFAULT_FRICTION_BAND_PP = 5.0
DEFAULT_MAX_DRAWDOWN = 0.20  # 报告侧兜底回撤上限(仅在诊断参考, 不做硬阻断)


# ---------------------------------------------------------------------------
# 基金风险类别(按量化特征聚类产出)
# ---------------------------------------------------------------------------
class RiskClass:
    LOW = "low"        # 低波动
    MED = "medium"     # 中波动
    HIGH = "high"      # 高波动

    # 允许的取值范围(供 WFA 网格搜索与二次校验用)
    TARGET_VOL_RANGE = {
        LOW: (0.05, 0.20),
        MED: (0.08, 0.25),
        HIGH: (0.10, 0.30),
    }
    # 分类动态回撤硬上限(MEMORY 已记录: 低/中 15%, 高 20-25%)
    MAX_DRAWDOWN_CAP = {
        LOW: 0.15,
        MED: 0.15,
        HIGH: 0.25,
    }


@dataclass
class FundStrategyConfig:
    """某类(或单基金)当前生效的策略参数。"""
    target_vol: float = DEFAULT_TARGET_VOL
    friction_band_pp: float = DEFAULT_FRICTION_BAND_PP
    risk_class: str = RiskClass.MED
    # 以下为溯源/审计字段
    source: str = "default"          # default | approved | explored
    proposal_id: Optional[int] = None  # 若来自 adaptive_proposal, 记录其 id
    note: str = "保守默认"            # 人类可读说明

    def to_dict(self) -> Dict:
        return {
            "target_vol": self.target_vol,
            "friction_band_pp": self.friction_band_pp,
            "risk_class": self.risk_class,
            "source": self.source,
            "proposal_id": self.proposal_id,
            "note": self.note,
        }


# 每类的保守默认(未自适应时: 全部用全局默认, 但可基于该类做细微修正)
_CLASS_DEFAULT: Dict[str, FundStrategyConfig] = {}


def class_default(risk_class: str) -> FundStrategyConfig:
    """某风险类别未批准任何自适应时的保守默认参数。"""
    if risk_class not in _CLASS_DEFAULT:
        # 保守起见, 高波动类 target 略低(求稳), 低波动类可略高
        tv = 0.12 if risk_class == RiskClass.HIGH else (
            0.15 if risk_class == RiskClass.MED else 0.17)
        _CLASS_DEFAULT[risk_class] = FundStrategyConfig(
            target_vol=tv,
            friction_band_pp=DEFAULT_FRICTION_BAND_PP,
            risk_class=risk_class,
            source="default",
            note=f"{risk_class} 波动类保守默认",
        )
    return _CLASS_DEFAULT[risk_class]


# ---------------------------------------------------------------------------
# 分类工具: 按历史净值序列量化特征聚类
# ---------------------------------------------------------------------------
def classify_fund(navs) -> str:
    """
    根据基金历史净值序列(可迭代对象, 元素带 .nav 属性)计算年化波动率,
    依阈值返回 低/中/高 波动类别。

    波动率口径(简化为近一年日收益标准差年化), 与 analyzer 一致避免引入新概念。
    """
    if not navs:
        return RiskClass.MED
    navs = list(navs)
    if len(navs) < 20:
        return RiskClass.MED

    # 取最近一年(约250个交易日)算年化波动
    recent = navs[-250:] if len(navs) > 250 else navs
    rets = []
    prev = None
    for n in recent:
        v = getattr(n, "nav", None)
        if v is None or v <= 0:
            continue
        if prev is not None and prev > 0:
            rets.append(v / prev - 1.0)
        prev = v
    if len(rets) < 10:
        return RiskClass.MED

    import math
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    daily_vol = math.sqrt(var)
    ann_vol = daily_vol * math.sqrt(252)

    # 阈值(年化波动率): <15% 低, <25% 中, >=25% 高
    if ann_vol < 0.15:
        return RiskClass.LOW
    if ann_vol < 0.25:
        return RiskClass.MED
    return RiskClass.HIGH

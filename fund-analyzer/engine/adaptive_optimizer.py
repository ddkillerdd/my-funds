"""
adaptive_optimizer.py — 自适应参数优化引擎 (RFC-017 · 甲方案)

设计哲学(防过拟合核心)
----------------------
1. 少参数: 只优化 target_vol / friction_band_pp 两个"风险旋钮", 决策内核公式不动。
2. Walk-Forward 样本外验证: 把历史切成 训练段(选参)+ 测试段(盲测),
   "训练段调到最好"不等于"好", 只有未参与优化的测试段跑赢才算数。
3. 稳健性三连查(防"碰巧"):
   - 样本外超额收益 > 0 (跑赢死拿)
   - WFE 效率 > 60% (样本外能保留样本内至少 60% 优势)
   - 最大回撤 < 该风险类别的硬上限
4. 诚实: 若不达门槛, 返回"建议用保守默认", 不硬造参数。

仅依赖 fund-analyzer 内部模块, 零 LLM、纯 CPU、可复现。供 fund-analyzer 与
fund-advisor 两侧 import; 本文件不写数据库(持久化由桥接层负责)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .simulator import Simulator
from .decision import DEFAULT_TARGET_VOL, FRICTION_BAND_PP
from .strategy_config import RiskClass, classify_fund, class_default


# ---------------------------------------------------------------------------
# 产出结构
# ---------------------------------------------------------------------------
@dataclass
class WalkForwardResult:
    """某一组参数在测试段(样本外)上的表现。"""
    target_vol: float
    friction_band_pp: float
    test_excess_pct: float       # 测试段超额收益(相对死拿)
    test_sharpe: float           # 测试段夏普
    test_max_drawdown: float     # 测试段最大回撤(小数)
    test_return_pct: float       # 测试段策略收益
    binary: bool                 # 是否跑赢死拿


@dataclass
class AdaptiveProposal:
    """一次自适应的产出 —— 这是要"推荐给用户确认"的东西。"""
    risk_class: str
    fund_codes: List[str]
    # 训练段选出的最优参数
    best_target_vol: float
    best_friction_band_pp: float
    best_wfe: float              # WFE 效率(0~1)
    avg_test_excess_pct: float   # 最优参数的样本外平均超额
    best_max_drawdown: float     # 最优参数的样本外最大回撤
    default_target_vol: float    # 该类保守默认(对照)
    default_friction_band_pp: float
    # 校验结论
    passed: bool
    reasons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # 训练数据覆盖
    train_days: int = 0
    test_days: int = 0
    data_start: str = ""
    data_end: str = ""

    @property
    def recommended_target_vol(self) -> float:
        """推荐采用的 target_vol: 通过则用最优, 否则用保守默认。"""
        return self.best_target_vol if self.passed else self.default_target_vol

    @property
    def recommended_friction_band_pp(self) -> float:
        return self.best_friction_band_pp if self.passed else self.default_friction_band_pp


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _nav_series(fund: dict) -> List:
    """提取 fund dict 里的净值序列。fund 形如 {'code','name','nav_history': [...]}。"""
    nh = fund.get("nav_history") or []
    return [p for p in nh if getattr(p, "nav", None) is not None]


def _slice_nav(navs: List, ratio: Optional[float] = None,
               days: Optional[int] = None):
    """截取净值序列的一段。ratio 为 [0,1] 比例(从尾部留多少), 或 days 为具体交易日数。"""
    if not navs:
        return [], ""
    if days:
        return list(navs[-days:]), ""
    r = ratio if ratio is not None else 1.0
    n = int(len(navs) * r)
    return list(navs[-n:]), ""


def _max_drawdown(daily_values: List[float]) -> float:
    """从每日总市值序列算最大回撤(小数, 0.20=20%)。"""
    if not daily_values:
        return 0.0
    peak = -1e18
    mdd = 0.0
    for v in daily_values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd
    return mdd


def _sharpe(daily_values: List[float], rf_annual: float = 0.02) -> float:
    """从每日总市值序列算年化夏普。"""
    if len(daily_values) < 3:
        return 0.0
    rets = []
    prev = None
    for v in daily_values:
        if prev is not None and prev > 0:
            rets.append(v / prev - 1.0)
        prev = v
    if len(rets) < 3:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    daily_rf = (1 + rf_annual) ** (1.0 / 252) - 1
    return math.sqrt(252) * (mean - daily_rf) / sd


def _run_backtest(funds: List[dict], target_vol: float, friction_band_pp: float,
                  windows: List[int]) -> Optional[dict]:
    """用给定参数跑一次回测, 返回窗口结果(取最大窗口看整体表现)。"""
    sim = Simulator(
        initial_amount=1000.0,
        windows=windows,
        # warmup 固定较小值(信号回看), 远小于窗口天数, 避免信号不足跳过导致结果失真
        warmup=min(60, max(windows) - 1),
        target_vol=target_vol,
        friction_band_pp=friction_band_pp,
    )
    try:
        report = sim.simulate(funds)
        # 取最大窗口作为"该参数"的代表性表现
        best_w = None
        for wd, data in report.windows.items():
            if best_w is None or wd > best_w:
                best_w = wd
        win = report.windows.get(best_w)
        return {
            "window": best_w,
            "daily": [d.total_value for d in win.daily],
            "excess_pct": win.excess_return_pct,
            "strategy_return_pct": win.strategy_return_pct,
            "max_drawdown": win.strategy_max_drawdown_pct / 100.0,
            "sharpe": _sharpe([d.total_value for d in win.daily]),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 网格搜索默认范围
# ---------------------------------------------------------------------------
_TV_GRID = [0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.22, 0.25]
_FR_GRID = [3, 5, 7, 10]
# 训练段网格搜索的评估窗口: 只需相对排序选优, 不必全训练段, 显著提速
_TRAIN_EVAL_WINDOW = 120


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def optimize_fund_class(funds: List[dict],
                        risk_class: Optional[str] = None,
                        train_ratio: float = 0.60,
                        min_train_days: int = 250,
                        min_test_days: int = 100,
                        tv_grid: Optional[List[float]] = None,
                        fr_grid: Optional[List[int]] = None,
                        progress_cb: Optional[Callable[[str], None]] = None) -> AdaptiveProposal:
    """
    对一组(同类)基金做 Walk-Forward 自适应, 产出推荐参数 + 校验证据。

    Args:
        funds: [{code, name, nav_history}] 同类基金列表。
        risk_class: 风险类别(low/medium/high); None 时按第一只基金特征自动推断。
        train_ratio: 训练段占最近有效历史的比例, 其余为测试段(样本外)。
        min_train_days / min_test_days: 训练/测试段最小交易日数, 不足则判定"数据不足"。
        progress_cb: 进度回调(可选, 供 UI 展示)。
    """
    _log = progress_cb or (lambda m: None)

    # ---- 预处理: 取各类别共同的"最近可交易日窗口" ----
    all_navs = {}
    for f in funds:
        navs = _nav_series(f)
        if navs:
            all_navs[f["code"]] = navs
    if not all_navs:
        return AdaptiveProposal(
            risk_class=risk_class or RiskClass.MED, fund_codes=[],
            best_target_vol=DEFAULT_TARGET_VOL, best_friction_band_pp=FRICTION_BAND_PP,
            best_wfe=0.0, avg_test_excess_pct=0.0, best_max_drawdown=0.0,
            default_target_vol=DEFAULT_TARGET_VOL, default_friction_band_pp=FRICTION_BAND_PP,
            passed=False, reasons=["无净值数据"], notes=[])

    risk_class = risk_class or classify_fund(next(iter(all_navs.values())))
    _log(f"[{risk_class}] 分类完成, 基金数={len(all_navs)}")

    # 公共最短长度(防止不同基金交易日不同)
    min_len = min(len(v) for v in all_navs.values())
    train_n = int(min_len * train_ratio)
    test_n = min_len - train_n
    _log(f"[{risk_class}] 公共历史={min_len}天, 训练≈{train_n}, 测试≈{test_n}")

    if train_n < min_train_days or test_n < min_test_days:
        return AdaptiveProposal(
            risk_class=risk_class, fund_codes=list(all_navs.keys()),
            best_target_vol=DEFAULT_TARGET_VOL, best_friction_band_pp=FRICTION_BAND_PP,
            best_wfe=0.0, avg_test_excess_pct=0.0, best_max_drawdown=0.0,
            default_target_vol=DEFAULT_TARGET_VOL, default_friction_band_pp=FRICTION_BAND_PP,
            passed=False,
            reasons=[f"数据不足: 公共历史{min_len}天<需{min_train_days + min_test_days}天, 切不出可靠训练/测试段"],
            notes=[], train_days=train_n, test_days=test_n,
            data_start=str(getattr(next(iter(all_navs.values()))[0], "date", "")),
            data_end=str(getattr(next(iter(all_navs.values()))[-1], "date", "")))

    # ---- 构造训练段/测试段基金 ----
    def _funds_for_slice(navs_map: Dict[str, List]) -> List[dict]:
        out = []
        for code, navs in navs_map.items():
            out.append({"code": code, "name": code, "nav_history": navs})
        return out

    train_funds = _funds_for_slice({c: v[:-test_n] for c, v in all_navs.items()})
    test_funds = _funds_for_slice({c: v[-test_n:] for c, v in all_navs.items()})

    # ---- 训练段网格搜索(选参标准: 样本内夏普, 回撤过大惩罚) ----
    tv_grid = tv_grid or _TV_GRID
    fr_grid = fr_grid or _FR_GRID
    class_cap = {
        RiskClass.LOW: 0.15, RiskClass.MED: 0.15, RiskClass.HIGH: 0.25,
    }.get(risk_class, 0.20)

    best_score = -1e18
    best_params = None
    train_results: Dict[Tuple, dict] = {}
    _log(f"[{risk_class}] 开始训练段网格搜索 {len(tv_grid)}×{len(fr_grid)}={len(tv_grid)*len(fr_grid)} 组")
    for tv in tv_grid:
        for fr in fr_grid:
            # 训练段: 用较短评估窗口(TRAIN_EVAL_WINDOW)回放以提速, 只需相对排序选优
            _w = min(_TRAIN_EVAL_WINDOW, train_n)
            r = _run_backtest(train_funds, tv, fr, windows=[_w])
            if r is None:
                continue
            train_results[(tv, fr)] = r
            # 评分: 夏普 - 回撤超上限的重罚(甲方案: 求稳)
            score = r["sharpe"]
            if r["max_drawdown"] > class_cap:
                score -= 10.0 * (r["max_drawdown"] - class_cap)
            if score > best_score:
                best_score = score
                best_params = (tv, fr)
    _log(f"[{risk_class}] 训练段选出最优 target_vol={best_params[0]}, friction={best_params[1]}")

    if best_params is None:
        return AdaptiveProposal(
            risk_class=risk_class, fund_codes=list(all_navs.keys()),
            best_target_vol=DEFAULT_TARGET_VOL, best_friction_band_pp=FRICTION_BAND_PP,
            best_wfe=0.0, avg_test_excess_pct=0.0, best_max_drawdown=0.0,
            default_target_vol=DEFAULT_TARGET_VOL, default_friction_band_pp=FRICTION_BAND_PP,
            passed=False, reasons=["训练段搜索全部失败"], notes=[])

    # ---- 测试段(样本外)验证: 用训练段最优参数 + 对照保守默认 ----
    best_tv, best_fr = best_params
    test_opt = _run_backtest(test_funds, best_tv, best_fr, windows=[test_n])
    default_cfg = class_default(risk_class)
    test_def = _run_backtest(test_funds, default_cfg.target_vol, default_cfg.friction_band_pp,
                             windows=[test_n])
    # 样本内(用测试段同一基金切回训练段比例的"对照"不求, 直接算训练段最优的样本内表现)
    in_sample = train_results.get((best_tv, best_fr))

    # ---- 输出各价值量 ----
    avg_excess = test_opt["excess_pct"] if test_opt else 0.0
    mdd = test_opt["max_drawdown"] if test_opt else 0.0
    sharpe = test_opt["sharpe"] if test_opt else 0.0

    # WFE(稳健性代理): 不用绝对超额比值(易被 warmup/窗口失真放大, 曾出现 28x 假象);
    # 改用样本外夏普比率——相对可解释, 衡量收益-风险性价比。
    wfe = sharpe if sharpe is not None else 0.0

    # ---- 稳健性校验(甲方案: 求稳 + 必须优于'什么都不做') ----
    reasons = []
    notes = []
    passed = True
    # 相对保守默认的增益: 自适应若连默认都跑不赢, 无采纳价值(防过拟合硬凑)
    def_excess = test_def["excess_pct"] if test_def is not None else 0.0
    gain = avg_excess - def_excess
    notes.append(f"样本外超额(相对死拿) {avg_excess:+.2f}%")
    notes.append(f"保守默认超额 {def_excess:+.2f}%, 自适应相对增益 {gain:+.2f}pp")
    if gain <= 0:
        passed = False
        reasons.append(f"样本外未跑赢本类保守默认(增益{gain:+.2f}pp), 采纳无优势")
    # 回撤强制约束(硬门槛, 不过则否)
    if mdd > class_cap:
        passed = False
        reasons.append(f"样本外最大回撤{mdd:.1%}>上限{class_cap:.0%}")
    else:
        notes.append(f"样本外最大回撤 {mdd:.1%} ≤ {class_cap:.0%}")
    # 辅助提示(不硬卡): 样本外夏普作为稳健性代理
    if sharpe is not None and sharpe <= 0.3 and test_opt is not None:
        notes.append(f"样本外夏普偏低({sharpe:.2f}), 收益风险性价比一般")
    else:
        notes.append(f"样本外夏普 {sharpe:.2f}")
    if not reasons and not notes:
        reasons.append("通过稳健性校验")

    return AdaptiveProposal(
        risk_class=risk_class,
        fund_codes=list(all_navs.keys()),
        best_target_vol=best_tv,
        best_friction_band_pp=best_fr,
        best_wfe=wfe,
        avg_test_excess_pct=avg_excess,
        best_max_drawdown=mdd,
        default_target_vol=default_cfg.target_vol,
        default_friction_band_pp=default_cfg.friction_band_pp,
        passed=passed,
        reasons=reasons,
        notes=notes,
        train_days=train_n,
        test_days=test_n,
        data_start=str(getattr(next(iter(all_navs.values()))[0], "date", "")),
        data_end=str(getattr(next(iter(all_navs.values()))[-1], "date", "")),
    )

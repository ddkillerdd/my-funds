# RFC-016 · 组合策略回测引擎 `engine/simulator.py`

> 状态: 已实现 (2026-08-02) · 类型: **与分析模块平级的一等公民**
> 模块: `fund-analyzer/engine/simulator.py` / 报告模型在 `engine/models.py` / 已导出
> 目的: 为分析模块提供一个**可复用、可进化、能出报告**的历史回测/模拟层，验证决策引擎
> (`decision.py` + `quant.py` + `analyzer`) 是否真能带来盈利。零 LLM、纯 CPU、幂等。

## 0. 一等公民 = 分析模块那样用

回测不是藏在 engine 里的一套散函数，而是**像分析模块一样的一等入口**：

| 分析模块 | 回测模块 (RFC-016) |
|---------|-------------------|
| `Analyzer` 类 | **`Simulator`** 类 |
| 顶层 `analyze(...)` 便捷函数 | **顶层 `simulate(...)`** 便捷函数 |
| 产出 `AnalysisReport` | 产出 **`BacktestReport`** |
| `engine/__init__.py` 导出 | 导出 `Simulator` + 报告模型 |

```python
from engine.simulator import simulate, Simulator
report = simulate(funds, initial_amount=200.0, windows=[30, 90, 365])
# 或类方式
sim = Simulator(initial_amount=200.0, windows=[30, 90, 365])
report = sim.simulate(funds)
# 消费
report.summary["avg_excess_pct"]            # 多窗口平均超额
report.windows[365].strategy_return_pct      # 近一年动态调仓收益
report.windows[90].daily[-1].actions         # 最近一日各基金动作
```

---

## 1. 为什么需要

分析模块 (`advisor_service.py` + `decision.py`) 每天给出"买/减/清仓 + 目标权重"。
但**它是否真能盈利，只有历史回测能回答**。此前没有任何验证手段，用户也不敢
录真实持仓。RFC-016 补上这一环：

- 拿**历史净值**回放"如果过去 N 天我们按引擎的加/减动作调仓，结果 vs 一直不动"。
- 新增基金即插即用: 只要 `fund_nav_history` 有数据，就能跑任意时间窗。
- 用和分析**同源**的信号 (`compute_all` + `build_position_action` + `_detect_regime`)，
  保证"回测的策略 = 日常在跑的策略"。

## 2. 核心设计原则

1. **点内无前视偏差**：每天的状态**只用 `<= 当天` 的数据**算信号。
   回放日期 `d` 的净值、指标、动作都只依赖 `d` 及之前的点。warmup 不足就跳过该日。
2. **与分析模块同源**：信号来自 `quant.compute_all`、动作来自 `decision.build_position_action`、
   牛熊判断来自 `analyzer._detect_regime`——不是一套"考试专用"的简化逻辑。
3. **零 LLM、纯 CPU、幂等**：同数据永远同结果，秒级出，可反复跑、可进 CI。
4. **组合级再平衡**：模拟的是"整个组合动态调仓"，不是单只基金孤立模拟；
   每日按目标权重把总资产重新分配，余量进现金。
5. **可进化**：策略 (`strategy`) 与执行器 (`executor`) 都是可注入参数，可随时替换/叠加。

## 3. 三个数据正确性要点（否则结果全错）

| 陷阱 | 错误做法 | 正确做法 |
|------|---------|---------|
| 回放日历 | 只取一只基金的日期序列 | 取**所有基金日期并集**（各基金交易日不同） |
| 不同基金交易日不同 | 用 `dict.get(d)` 缺日当 0 | **carry-forward** 最近已知净值（既不视 0 也不用到未来） |
| 最后交易日错位 | `get(d_last)` 返回 None → 0 | `_build_last_known_value` 按并集日历向前填充，保证每一天都有条目 |

> 这三条是回测最容易错、错得最隐蔽的地方——曾经把基准算成 -28%（实际 -5%），
> 因为 018044 最后净值在 07-30、别的在 07-31，`get('07-31')` 返回 None 被当 0。

## 4. 模块组成

### 4.1 数据结构

- `NavPoint(date, nav)` — 复用 `models.py`。
- `SimDayResult(date, total_value, cash, holdings_value, actions, target_weights)` — 单日快照。
- `SimWindowResult(window_days, start_date, end_date, buy_hold_return_pct,
  strategy_return_pct, excess_return_pct, max_drawdown_pct,
  buy_hold_max_drawdown_pct, daily, final_weights)` — 单窗口汇总。

### 4.2 主入口
```python
simulate_portfolio(
    funds: List[Dict],          # [{"code","name","nav_history":[NavPoint,...]}]
    initial_amount=50.0,
    windows=[30, 90, 365],
    warmup=252,
    target_vol=0.15,
    friction_band_pp=5.0,
    strategy=None, executor=None,
) -> Dict[int, SimWindowResult]
```
- `windows` 是**回放日历长度**（步进天数）；信号永远用全历史（warmup 252 天）计算，
  窗口只决定"从哪天开始回放"。
- 返回 `{窗口天数: SimWindowResult}`，可对比 30/90/365 三种周期。

### 4.3 内部函数
| 函数 | 作用 |
|------|------|
| `_detect_regime(qi)` | 牛/熊/震荡量化判断（与 analyzer 同源） |
| `_slice_history(navs, end_idx, warmup)` | 取 `[0,end_idx]` 点内历史，不足 warmup 返回 [] |
| `_build_last_known_value(histories, calendar)` | 构造 carry-forward 净值映射（正确性关键） |
| `_simulate_window(...)` | 单窗口回放主体（见 §3 正确性设计） |
| `_default_strategy(...)` | 调 `build_position_action` 产出动作 + 目标权重 |
| `_default_executor(shares, targets, nav, date, total)` | 按目标权重重分配份额，余量进现金 |
| `_max_drawdown(series)` | 最大回撤（%） |
| `build_funds_input(rows)` | 便捷把 `{code:[(date, nav),...]}` 转成 funds 输入 |

### 4.4 对外报告模型（`engine/models.py`，已导出）
| 模型 | 说明 |
|------|------|
| `SimDaySnapshot` | 单日快照：总市值/现金/持仓/目标权重/动作/当日净值 |
| `BacktestWindow` | 单窗口：收益/基准/超额/双回撤/期末权重/每日快照/per_fund |
| `BacktestReport` | 完整报告：多窗口字典 + `summary`(最优/最差/平均超额) + 初始配置 |

## 5. 使用示例

```python
from engine.simulator import simulate, build_funds_input

# rows: {code: [(date_str, nav), ...]}  从 fund_nav_history 拉取
funds = build_funds_input(rows)
report = simulate(funds, initial_amount=200.0, windows=[30, 90, 365], warmup=252)

for wd, w in report.windows.items():
    print(f"近{wd}天: 策略{w.strategy_return_pct:+.1f}% 基准{w.buy_hold_return_pct:+.1f}% "
          f"超额{w.excess_return_pct:+.1f}% 回撤{w.strategy_max_drawdown_pct:.1f}%")
# 多窗口汇总
print(report.summary)   # {best_excess_pct, worst_excess_pct, avg_excess_pct, windows}
```

## 6. 真实数据结果（2026-08-02，4 只测试基金，初始各 50 元）

| 窗口 | 动态调仓 | 买入持有 | 超额 | 策略回撤 | 基准回撤 |
|------|---------|---------|------|---------|---------|
| 近 30 天 (06-18~07-31) | **-7.0%** | -4.9% | -2.1% | 9.5% | 8.8% |
| 近 90 天 (03-20~07-31) | **+8.4%** | +2.6% | +5.8% | 9.5% | 11.0% |
| 近 365 天 (25-01-24~26-07-31) | **+16.3%** | -1.0% | +17.3% | 21.5% | 22.4% |

**诚实解读（不粉饰）：**
- ✅ 中长周期（90/365 天）策略**显著跑赢买入持有**（+5.8% / +17.3%），回撤还更低，
  说明引擎的调仓逻辑在趋势行情里有正贡献。
- ⚠️ **近 30 天小幅跑输**（-2.1%）：短期行情震荡时频繁调仓有摩擦损耗。
- ⚠️ **注意集中风险**：365 天回放期末权重收敛到 `100% 000311`（沪深 300 指数基金），
  即引擎把全部资产都调进了一只。这是**标的池过小（仅 4 只）+ 目标权重无持仓上限**
  共同导致——不是 bug，但意味着单一基金踩雷会放大。**建议后续加单基金持仓上限
  （如单只 ≤40%），并扩充候选池。**

## 7. 单元测试 `tests/test_simulator.py`

覆盖：多窗口结构、点内无前视、调仓目标一致性、regime 缺省、最大回撤、输入转换。
共 6 条，全引擎 146 passed。

## 8. 已知限制与下一步

- **只回测"资产配置"层面**，不含申购/赎回费、冲击成本、涨跌停限制（理想化执行）。
- **基金本身净值已含管理人运作**，回测的是"择时调仓"的边际价值。
- 下一步（待用户拍板）：
  1. 单基金权重上限（如 40%）防集中；
  2. 接真实指数序列到 `regime`，做更稳健的牛熊分层；
  3. 扩充候选基金池再回测；
  4. 把回测接到分析报告里（每日附一段"历史回测是否支持当前调仓动作"）。

## 9. 变更记录

- 2026-08-02: 初版实现 `simulator.py` + `test_simulator.py` + 本 RFC。
  修复了回测最隐蔽的两个正确性 bug：① 回放日历只用单只基金日期；
  ② 缺日被当 0 → 改为 carry-forward 最近已知净值（前者把基准从 -5% 错算成 -28%）。
- 2026-08-02: **升级为一等公民**——新增 `Simulator` 类 + 顶层 `simulate()`
  便捷函数，产出 `BacktestReport`（与分析模块 `Analyzer`/`analyze()`/`AnalysisReport`
  平级）；报告模型 `SimDaySnapshot`/`BacktestWindow`/`BacktestReport` 加入 `models.py`
  并从 `engine/__init__.py` 导出；测试改用新入口，全引擎 148 passed。

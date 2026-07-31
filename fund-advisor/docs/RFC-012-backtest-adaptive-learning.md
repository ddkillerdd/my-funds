# RFC-012 建议回测与自适应在线学习（Backtest & Adaptive Learning）

> 状态：**提议（待审阅）** · 日期：2026-07-31 · 目标版本：v6.2
> 所属仓库：my-funds（engine 独立 + 集成层内联）

## 1. 背景与目标

系统当前能生成建议（HOLD/REDUCE/INCREASE/WATCH），但**从不验证建议事后对不对**，也**不据此改进**。

本 RFC 实现闭环：

```
出建议 → 记录快照 → T+N 验证对错 → 累计命中率 → 校准置信度/视角权重 → 回流下次分析 → 越用越准
```

**核心目标：自适应/在线学习**——系统从自己的历史判断中学习，改进后续决策质量，而不只是报告准确率。

## 2. 关键原则（必须先定，防走歪）

### 2.1 分层约束：回测反馈"只能改决策层，不能改因子层"

| 层 | 内容 | 回测能否改 |
|----|------|-----------|
| **因子层** | Sharpe / 回撤 / MACD / 波动率 ... | ❌ **不可改**（纯数学，保持客观）|
| **决策/解读层** | 置信度、视角强调、健康分标签 | ✅ **可校准** |

**为什么**：因子是客观数学规律，用"猜对几次"去改会**过拟合 + 抖动**（样本太少，今天对就加权重，明天错又减，永远学不到真规律）。而决策层（置信度/重点）本就该反映"这套方法历史靠不靠谱"。

### 2.2 样本约束：报告目前只有 2 个报告日
- 7-30（18 份，调试空跑）+ 7-31（3 份，真实）
- 回测**只能面向未来积累**，不能回测过去（无跨期历史）

### 2.3 判定标准：相对基准，不判 HOLD/WATCH
- 用 **相对收益**（跑赢/跑输同期指数）而非绝对涨跌 → 避免"大盘跌20%减仓看着对，实际只是跟跌"
- **只判方向动作**（REDUCE/INCREASE 参与命中率），HOLD/WATCH 不参与（无方向判断，强行判失真）

## 3. 架构：引擎独立 + 集成层内联

```
fund-analyzer/engine/backtest.py        ← 纯判定逻辑(可单测, 独立)
fund-analyzer/engine/learning.py        ← 在线学习: 命中率→置信度/视角校准(纯逻辑)
        ↓ import
fund-advisor/backend/services/backtest_service.py  ← 接 DB + cron + 报告hook + 前端
```

- **不单独开项目**（不增进程/依赖，符合服务器 3.6G 约束）
- 纯逻辑独立可测，符合 monorepo"引擎 vs 集成层"分工

## 4. 数据表设计

### 4.1 `advice_snapshot`（建议快照，出报告时写入）

```sql
advice_snapshot:
  id
  report_id            -- 关联 advisor_report.id
  fund_code / fund_name
  action               -- REDUCE/INCREASE/HOLD/WATCH
  advice_date          -- 建议日
  nav_at_advice        -- 建议时净值
  change_pct           -- 建议调仓幅度%(如REDUCE -20%)
  market_phase         -- 建议时市场环境快照(可选: 牛/熊/震荡)
  status               -- pending / validated / expired
  validation_date
  fund_change_pct      -- 建议后基金涨跌%
  benchmark_change_pct -- 同期基准(沪深300)涨跌%
  relative_return      -- 基金涨跌 - 基准涨跌
  verdict              -- hit / miss / neutral (对/错/中性)
```

### 4.2 `factor_hit_rate`（因子/视角命中率表，在线学习的状态）

```sql
factor_hit_rate:
  factor_key           -- 如 'trend', 'risk', 'value', 'tech', 'sharpe', 'drawdown'
  action_type          -- REDUCE / INCREASE
  total / hits / miss
  hit_rate
  rolling_window       -- 滚动窗口(如最近20个判定)
  updated_at
```

## 5. 引擎模块

### 5.1 `backtest.py`
- `validate(advice, nav_before, nav_after, benchmark_before, benchmark_after) -> Verdict`
  - REDUCE: 相对收益 < 0（跌/跑输）→ hit；> 0 → miss；接近0 → neutral
  - INCREASE: 相对收益 > 0 → hit；< 0 → miss；接近0 → neutral
  - HOLD/WATCH: neutral（不参与）
- 计算：基金涨跌% / 基准涨跌% / 相对收益

### 5.2 `learning.py`（在线学习核心）
- `calibrate_confidence(hit_rate, sample_size) -> adjusted_conf`
  - 样本少(<10)：置信度向默认值收缩（保守，不过度自信）
  - 样本足：置信度 = f(命中率)
- `factor_weight_adjustment(factor_hit_rates) -> weights`
  - 输出"哪个视角历史更准"的权重提示，供解读层强调
- **防过拟合**：
  - 滚动窗口（只统计最近 N 个判定），旧数据衰减
  - 最小样本阈值，不足时回到默认置信度
  - 每份建议逐条独立验证，避免一次偏差污染全局

## 6. 集成层 `backtest_service.py`

| 方法 | 触发 | 职责 |
|------|------|------|
| `record_advice(report)` | AdvisorJob 出报告后 | 抓建议快照写 `advice_snapshot` |
| `validate_due()` | 每日 cron | 找 T+N 到期的 pending 建议，算涨跌对比基准，写 verdict |
| `refresh_hit_rates()` | 每日 | 重算各 factor/action 命中率到 `factor_hit_rate` |
| `get_stats()` | 前端/报告 | 返回命中率、分动作统计、组合 vs 基准 |
| `get_feedback()` | 分析时 | 读因子命中率 → 给解读层置信度校准/视角权重 |

## 7. 在线学习闭环（重点）

```
出建议(带默认置信度)
   ↓ record_advice 存快照
T+N 验证 → hit/miss
   ↓ validate_due + refresh_hit_rates
factor_hit_rate 更新
   ↓ get_feedback
下次分析时:
   · REDUCE建议的置信度 = 校准后(基于该factor历史命中率)
   · 解读层强调"历史更准的视角"
   · 提示语里可注明"该因子近20次减仓建议命中率70%"
```

**可视效果**：随着建议积累，系统会逐渐表现出——
- 某个视角历史很准 → 它在解读里显得更"笃定"（置信度高）
- 某个视角一直不准 → 系统对它的结论标注低置信度/弱化
- 用户能在报告里看到"该建议基于的历史命中率"

## 8. 验证周期与基准

- **验证周期**：T+20 交易日（约1个月），平衡噪音与样本积累速度
- **基准**：沪深300 指数（从现有 `market_data.py` 东财指数K线取）
- 纯逻辑用 NAV 数据，**与用户持仓份额无关**——即使当前 4 个基金是测试数据，只要持续出报告就能积累回测样本

## 9. 服务器约束下的实现

- 不装 pandas/akshare，用现有 `fund_nav_history` + 东财指数
- 复用现有每日 cron（FundAdvisor 每天跑，顺带 `validate_due` + `refresh_hit_rates`）
- 不新增常驻进程

## 10. 测试计划

- `engine/backtest.py`：REDUCE/INCREASE 的 hit/miss/neutral 边界（相对基准）
- `engine/learning.py`：样本少收缩置信度、命中率→置信度映射、滚动窗口衰减
- 集成：record_advice 落库、validate_due 正确判定、命中率更新、feedback 回流到报告

## 11. 实施范围与文件

| 层 | 文件 |
|----|------|
| 引擎 | `fund-analyzer/engine/backtest.py` / `learning.py` |
| schema | `fund-advisor/backend/schemas/backtest.py` |
| 模型 | `fund-advisor/backend/models/advice_snapshot.py` / `factor_hit_rate.py` |
| service | `fund-advisor/backend/services/backtest_service.py` |
| 报告hook | `advisor_service.py`（出报告后调 record_advice + 分析时注入 get_feedback）|
| cron | 复用现有 FundAdvisor cron |
| 前端(可选) | AdvisorView 加"回测/命中率"区块 |

## 12. 决策点（已确认）

1. ✅ **在线学习/自适应**为核心目标
2. ✅ **引擎独立 + 集成层内联**（monorepo 结构）
3. ✅ **相对基准判定**：跑赢/跑输沪深300，非绝对涨跌
4. ✅ **只判方向动作**：REDUCE/INCREASE 参与命中率，HOLD/WATCH 不参与（无方向，强判失真）
5. ✅ **三段式验证节奏**：每日记录观察值 → 每10天自动适应 → 可手动触发适应
6. ✅ **在线学习落地到报告可见**：报告显示该建议的历史命中率

### 三段式适应机制（决策点3落地）
```
每日 cron        → 抓最新净值, 已到验证期的建议判对错, 累计观察值(样本)
每10天(20:00)    → 跑一次"适应" = 用近10天累计命中率校准置信度/视角权重
手动触发         → 点一下立即适应(不等10天)
```
每日积累数据但**10天才适应一次**，是为了防抖动/过拟合（样本少时逐日校准会来回摆动）。

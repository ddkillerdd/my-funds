# FundAnalyzer · 分析引擎架构总览（RFC-005 ~ RFC-016）

> **定位**: FundAdvisor 的 **纯 Python 决策引擎库**（无 Web / ORM / API 依赖）。
> 两项目分工见 `../fund-advisor/ARCHITECTURE.md`（本文件聚焦引擎内部模块）。
> **配套**: `README.md`（用法）/ `DESIGN.md`（方法论+Schema）/ `docs/RFC-*.md`（决策文档）

---

## 一、引擎铁律

> **LLM 只做解读/叙事,不做评分。** 所有分数、买卖信号、择时结论由 **Python 量化** 计算(防幻觉)。
> 量化层先行(<1s,零 LLM),LLM 仅在量化结果上做多视角解读 + 辩论 + 叙事。

## 二、模块地图

```
engine/
├── quant.py            # 单基金 32 项量化指标 (Sharpe/回撤/波动/MACD/趋势/估值...)  [纯numpy]
├── portfolio_quant.py  # 组合层量化 (有效前沿/相关性/集中度/组合风险)             [RFC-009]
├── market_data.py      # 市场数据层 (东财指数K线/基金规模/估值分位/基准对比/cache) [RFC-009 C]
├── models.py           # Pydantic 数据模型 (QuantIndicators/FundHolding/Views...)
├── prompts.py          # 提示词模板 (含 DEBATE_PROMPT 决策矩阵)
├── llm_client.py       # LLM 调用封装 + fallback_debate 量化决策矩阵               [RFC-006/013]
├── analyzer.py         # 主流程编排 (5步: 量化→4视角→辩论→总评→历史对照)          [RFC-005/006]
├── decision.py         # 确定性动作决策 (四视角分数+regime感知+六档量化矩阵)       [RFC-013 B+R]
├── timing.py           # 择时引擎 (6流派→0-100 timing_score + risk_gate + dca)   [RFC-007]
├── screener.py         # 荐基六因子打分 + 权重重归一化 + 风格归因                 [RFC-008]
├── screen_runner.py    # 荐基端到端编排 (分批净值/去重/冗余惩罚)                  [RFC-008]
├── simulator.py        # 组合策略回测 (point-in-time 回放决策链路)                [RFC-016]
├── backtest.py         # 建议命中率评估 (advice hit/miss/neutral)                 [RFC-012]
└── learning.py         # 在线学习 (hit-rate→置信度/权重校准, 只调解读层不碰因子)  [RFC-012 §5]
```

## 三、数据流（一次完整分析）

```
holdings(输入)
   │
   ▼
quant.py + portfolio_quant.py    量化层 (Python, 32指标+组合指标, <1s)
   │
   ▼
llm_client.py + prompts.py       4视角 LLM 诊断 (每基金~16次调用)
   │
   ▼
analyzer.py 辩论综合             矛盾裁决 + 置信度标记
   │
   ▼
decision.py / timing.py          确定性动作 + 择时分数 (纯量化, LLM不参与)
   │
   ▼
标准 JSON 报告  →  fund-advisor 持久化到 advisor_report 表
```

## 四、分层职责

| 层 | 模块 | 是否调 LLM | 职责 |
|----|------|-----------|------|
| 量化计算 | quant / portfolio_quant | ❌ | 指标、风险、相关性、集中度 |
| 数据 | market_data | ❌ | 东财抓取、缓存、基准对比 |
| 解读 | llm_client / prompts / analyzer | ✅ | 多视角诊断、辩论、叙事 |
| 决策 | decision / timing | ❌ | 确定性动作与择时数值 |
| 荐基 | screener / screen_runner | ❌(纯量化) | 因子打分、端到端编排 |
| 回测/学习 | simulator / backtest / learning | 混合 | 策略回测、命中评估、在线校准 |

## 五、测试

`pytest tests/` — 101 用例全绿（fixtures 内置,不调真实 LLM/网络）：
`test_quant` / `test_portfolio_quant` / `test_analyzer` / `test_decision` /
`test_prompts` / `test_llm_client` / `test_timing` / `test_screener` / `test_market_data` / `test_simulator`

## 六、文档指引

- 方法论 + 报告 Schema: `DESIGN.md`
- 引擎 RFC: `docs/RFC-005(multi-model-debate)` / `RFC-006(quality)` / `RFC-007(timing)` / `RFC-008(screener)` / `RFC-009(architecture)` / `RFC-013(action-determinism)` / `RFC-014(decision-engine)` / `RFC-016(portfolio-simulator)`
- RFC-014 为双项目共用,此文件即唯一权威副本（fund-advisor/docs 下为软链）。

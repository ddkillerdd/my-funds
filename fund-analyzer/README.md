# FundAnalyzer — 独立基金量化分析引擎

## 定位

FundAdvisor 的分析核心模块，完全独立的 Python 库。

从「持仓分析器」升级为「持仓分析 + 荐基 + 择时」三位一体的投顾内核（见 `docs/RFC-009-recommendation-architecture.md` 总纲）：

- **持仓分析**（已有，RFC-005 多模型辩论 + RFC-006 质量强化）
- **荐基**（RFC-008 Fund Screener：筛「买什么」）
- **择时**（RFC-007 Entry Timing：判「何时买」）

**不依赖** FundAdvisor 的 Web 框架、数据库 ORM、API 路由。
**只依赖** pandas + numpy + httpx（全部已有）。

```
FundAdvisor (调用方)
    │
    ├── import fund_analyzer
    ├── analyzer = Analyzer(api_config)
    └── report = analyzer.analyze(portfolio)
         ↑
         └── 标准 JSON，直接存 advisor_report 表
```

## 核心思路

```
量化计算 (Python, <1s)      →  LLM 4视角诊断 (nemotron, ~80s)  →  辩论综合 → 报告
     │                              │
  32项指标                      每个视角独立判断                 矛盾裁决
  零LLM参与                    每条引用具体数据                 置信度标记
```

**借鉴的顶级项目**：

| 来源 | 核心方法论 |
|------|-----------|
| TradingAgents (95K⭐) | 多角色分析 → Bull/Bear 辩论 → 基金经理决策 |
| ai-hedge-fund (50K⭐) | 18 位投资大师风格模拟 → 加权汇总 |
| FinRobot (学术论文) | Data-CoT → Concept-CoT → Thesis-CoT 三层链 |
| DX Research | Prompt 顺序决定引用率 (74% vs 3%) |
| pyfolio (Quantopian) | 专业级风险/收益指标标准 |

## 输入

```python
{
    "holdings": [
        {
            "fund_code": "161725",
            "fund_name": "招商中证白酒指数C",
            "current_mv": 10000.0,
            "cost": 9500.0,
            "mv_ratio": 25.0,
            "nav_history": [
                {"date": "2026-06-01", "nav": 1.2000},
                ...
            ]
        },
        ...
    ],
    "benchmark_nav_history": [...]  # 可选
}
```

## 输出

标准 JSON，包含：

| 区块 | 内容 | 产生方式 |
|------|------|---------|
| `ground_truth` | 32 项量化指标 + 组合指标 | Python 计算 |
| `per_fund_diagnosis` | 4 视角诊断 + 辩论综合 | LLM |
| `portfolio_diagnosis` | 组合健康度 + 调仓建议 | LLM |
| `confidence` | 全局置信度 + 警告 | 综合 |
| `completeness` | 指标完成度 + 缺失项 | 自动 |
| `historical_comparison` | 相对上次的变化 | DB 查询 |
| `degradation` | 降级标记 | 自动 |

详细 Schema: `DESIGN.md`

## 目录结构

```
fund-analyzer/
├── README.md              # 本文
├── DESIGN.md              # 完整设计文档 (调研、架构、Schema)
├── REQUIREMENTS.md
├── engine/
│   ├── models.py          # 数据类定义
│   ├── quant.py           # 量化指标 (32项)
│   ├── portfolio_quant.py # 组合指标
│   ├── prompts.py         # LLM Prompt 模板
│   ├── llm_client.py      # LLM 调用封装
│   └── analyzer.py        # 主流程编排
├── tests/
│   ├── fixtures/
│   ├── test_quant.py
│   ├── test_analyzer.py
│   └── conftest.py
└── docs/
```

## 开发状态

| 模块 | 代码 | 文档 |
|------|------|------|
| 量化层 quant.py (32指标) | ✅ 已实现 | DESIGN.md |
| 多模型辩论 RFC-005 | ✅ 已实现 | docs/RFC-005 |
| 分析质量强化 RFC-006 | ✅ 已实现 | docs/RFC-006 |
| 入场时机 RFC-007 | ✅ 已实现 `engine/timing.py` | docs/RFC-007 |
| 市场数据层 RFC-009 Phase C | ✅ 已实现 `engine/market_data.py` | docs/RFC-009 |
| 荐基引擎 RFC-008 | ✅ 已实现 `engine/screener.py` + `screen_runner.py` | docs/RFC-008 |
| 重构总纲 RFC-009 | ✅ 已落地 | docs/RFC-009 |

测试：`pytest tests/` — 99 个用例全绿（含 timing 17 / screener 15 / market_data 9）。

## 文档索引

- `DESIGN.md` — 核心方法论 + 架构（多轮调研验证）
- `docs/RFC-005-multi-model-debate.md` — 多模型辩论
- `docs/RFC-006-analysis-quality.md` — 分析质量与操作建议强化
- `docs/RFC-007-entry-timing-recommendation.md` — 入场时机推荐
- `docs/RFC-008-fund-screener.md` — 荐基引擎
- `docs/RFC-009-recommendation-architecture.md` — 重构总纲

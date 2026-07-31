# FundAdvisor · 项目架构总纲（v6.0.2 最终状态）

> **定位**: 个人基金"筛 → 择 → 配 → 析"四位一体投顾内核（RFC-009 总纲定调）
> **最终更新**: 2026-07-31（v6.0.2b，超时平衡后）
> **配套**: `PROJECT.md`（详细规格）/ `DEVLOG.md`（开发日志）/ `docs/RFC-*.md`（决策文档）

---

## 一、项目定位

FundAdvisor 是一个 **独立运行的 Web 服务**（backend :8200 + frontend :8201），
其核心决策能力来自 **fund-analyzer**（纯 Python 决策引擎库，无服务依赖）。
两者通过 **源码引用桥接**，不是微服务调用。

### 三位一体能力
| 环节 | 英文 | 引擎模块 | 说明 |
|------|------|----------|------|
| **筛** | Screen | `screener.py` + `screen_runner.py` | 六因子打分选基 |
| **择** | Time | `timing.py` | 择时买卖信号（现在能买吗）|
| **配** | Allocation | `portfolio_quant.py` + 组合诊断 | 组合配置/风险分配 |
| **析** | Analyze | `analyzer.py` + `llm_client.py` | LLM 多视角解读持仓 |

> **铁律**: LLM 只做解读/叙事，**不做评分**。所有分数、买卖信号、
> 择时结论均由 Python 量化计算（防幻觉）。

---

## 二、两大仓库分工

```
fund-analyzer/  (决策引擎库)
├── engine/
│   ├── quant.py            # 32指标量化计算 (Sharpe/回撤/波动/MACD/趋势...)
│   ├── portfolio_quant.py  # 组合层量化 (有效前沿/相关性/集中度)
│   ├── market_data.py      # 市场数据层 (东财指数K线/基金规模/估值分位/基准对比/cache)
│   ├── screener.py         # 荐基六因子打分 + 权重重归一化 + 风格归因
│   ├── screen_runner.py    # 荐基端到端编排 (分批净值/去重/冗余惩罚)
│   ├── timing.py           # 择时 (技术/趋势/回撤/情绪/估值 因子 + risk_gate + dca)
│   ├── analyzer.py         # 全量分析编排 (多视角→辩论→总评)
│   ├── llm_client.py       # LLM 调用 + fallback_debate 量化决策矩阵
│   ├── prompts.py          # 提示词 (含 DEBATE_PROMPT 决策矩阵)
│   └── models.py           # Pydantic 数据模型 (QuantIndicators/Views...)
└── tests/                  # 101 个测试全绿

fund-advisor/  (Web 服务)
├── backend/
│   ├── main.py             # FastAPI 入口
│   ├── api/                # 路由 (advisor/analysis/dashboard/holdings/nav/funds/imports/recommend)
│   ├── services/           # 服务层
│   │   ├── advisor_service.py   # ★ AI 分析核心 (model 分配/超时/降级)
│   │   ├── recommend_service.py # ★ 桥接 screener+timing 到 API
│   │   └── nav_fetcher.py       # 东财数据抓取 (唯一数据源)
│   ├── scheduler/          # 定时任务 (advisor_job 每日分析+邮件)
│   ├── models/             # SQLAlchemy ORM (含 email_send_record 幂等锁)
│   └── schemas/            # Pydantic API schema (含 advisor_recommend)
└── frontend/               # Vue3 + Vite + Element Plus
    └── src/
        ├── views/          # AdvisorView(报告) / RecommendView(荐基) / Holdings / Analysis / Dashboard
        └── api/index.js    # API client
```

---

## 三、模块关联（★分析与荐基如何与整体耦合）

### 3.1 依赖关系总览

两条业务管线（**分析**、**荐基**） + 一个**择时**能力，
都建立在同一套**量化底层**之上。谁都不孤立，共享根基：

```
                ┌─────────────────────────────────────────────┐
                │           fund-analyzer (决策引擎库)          │
                │                                             │
                │   【共享根基】 models.py ──── quant.py        │
                │   (数据模型定义)      └── portfolio_quant.py  │
                │           Pydantic/Dataclass  32指标+组合指标   │
                ├─────────────────────────────────────────────┤
                │                                             │
  分析管线        │    analyzer.py ──┬─ llm_client.py            │
  ✓✓✓✓✓         │                  └─ (多视角→辩论→总评)        │
                │                                             │
  荐基管线        │    screener.py ◄── screen_runner.py         │
  ✓✓✓✓✓         │                   └──┐   └─ market_data.py   │
                │                       └ 端到端编排(分批+排序)    │
                │                                             │
  择时能力        │    timing.py ──(独立调用 quant 因子)          │
  ✓✓✓           │                                             │
                └──────────────┬──────────────────────────────┘
                               │ sys.path 源码引用
                               ▼
                ┌─────────────────────────────────────────────┐
                │        fund-advisor (Web 服务)               │
                │  advisor_service   → 调 analyzer (分析)      │
                │  recommend_service → 调 timing + screen_runner│
                │  nav_fetcher       → 东财数据源(唯一)          │
                └─────────────────────────────────────────────┘
```

### 3.2 数据契约（模块间传递什么）

所有模块通过 **`QuantIndicators`** 这个统一数据对象交互，这是耦合的"接口契约"：

| 字段 | 含义 | 由谁算 | 被谁消费 |
|------|------|--------|----------|
| `efficiency.sharpe_ratio` | 风险调整收益 | quant.py | 分析(debate)/择时/荐基 |
| `risk.current_drawdown_pct` | 当前回撤 | quant.py | 分析/择时/决策矩阵 |
| `risk.max_drawdown_pct` | 最大回撤 | quant.py | 决策矩阵(豁免判断) |
| `trend.trend_direction` | 趋势方向 | quant.py | 分析/择时 |
| `macd.signal` | MACD 信号 | quant.py | 分析/择时/决策矩阵 |
| `nav_history` | 净值序列 | 东财/nav_fetcher | 所有模块的输入源 |

> **核心**: 分析、择时、荐基**共用 quant.py 的 `compute_all()`** 产出指标，
> 只是从不同角度消费这些指标。所以三者的量化判断天然一致（同源）。

### 3.3 调用链（一次荐基请求全流程）

**荐基 screen**（`POST /recommend/screen`）：
```
前端 RecommendView
  → 后端 recommend_service.screen_candidates()
    → engine.screen_runner (端到端编排)
        → engine.market_data   抓取候选基金净值+规模+估值
        → engine.quant.compute_all  算 32 指标
        → engine.screener.screen   六因子打分+风格归因+冗余惩罚
        → 输出 [FundScore] → 回前端排序展示
```

**择时 timing**（`POST /recommend/timing`）：
```
前端 → recommend_service.get_timing()
  → engine.screen_runner.fetch_fund_nav_full  (复用荐基的抓取)
  → engine.quant.compute_all
  → engine.timing.compute_entry_recommendation (五因子+risk_gate+dca)
  → 输出 买/卖/观/避 + 置信度
```

**分析 analyze**（每日 cron / 手动）：
```
cron/手动 → advisor_service._analyze_v3
  → engine.analyzer (逐基金)
      → engine.quant.compute_all   (同样指标)
      → engine.llm_client 每视角解读 → 辩论 → fallback_debate
  → 组合层 portfolio_quant + 总评
  → 写 advisor_report + 邮件推送
```

### 3.4 关键：三个模块为什么"同源同判"

- 都吃**同一份量化指标**（quant.compute_all 的输出）
- 都受 **`fallback_debate` 决策矩阵**约束（LLM 失效时的最后裁判）
- 数据源唯一（东财经 nav_fetcher/market_data），无多源打架

所以：**荐基筛出的好基金，择时也会判"能买"，分析也会给高分**——
三者天然对齐，不会出现"荐基推荐但分析看空"的自相矛盾。
这正是四位一体架构的价值。

---

## 四、数据流（核心：每日分析链路）

```
[东财 API] 唯一数据源
    │  nav_fetcher.py / market_data.py 抓取
    ▼
[MySQL fund_advisor]  (fund / nav_history / holding / advisor_report ...)
    │
    ▼
[advisor_service._analyze_v3]   ← 每日 09:00 cron 触发 / 手动触发
    │  每只基金 → 7个视角量化拆分
    │  每视角 → LLM 解读 (nano-9b 主力)
    │  多视角 → 辩论(debase) → 共识 → 动作建议
    │  组合层 → 总评/再平衡建议
    ▼
[advisor_report 表]  →  前端 /advisor 报告页可查全部历史
    ▼
[mail_service]  →  QQ 邮件推送 (幂等锁防重复发送)
```

---

## 五、LLM 模型链路（经 NewAPI 中转）

| 角色 | 模型 | 稳定性实测 | 用途 |
|------|------|-----------|------|
| **主力** | `nvidia/nemotron-nano-9b-v2` | ✅ 0% 超时 | 全部 7 视角首选 |
| **兜底1** | `nemotron-3-nano-omni-30b-reasoning` | ⚠️ 52% 超时 | fallback |
| **兜底2** | `deepseek-v4-flash` | ❌ 100% 超时 | fallback（已绕开）|

**超时平衡**（v6.0.2b 关键调优）:
- `default_timeout = 45s` / `fallback_timeout = 60s`
- 实测 NIM 真实推理请求需 37-44s 返回 → 45s 是"不误杀慢请求"的最优平衡点
- 之前 35s 太激进（误杀 40s+ 的请求）、60s 太慢（ds-flash 死等）

**降级策略**: llm_client.call() 传 `model=` 只试该模型；各视角首选失败后
由 analyzer 内部写死的 fallback 链处理；全失败走 `fallback_debate` 量化决策矩阵。

---

## 六、量化决策矩阵（防幻觉核心）

### `fallback_debate`（LLM 辩论失败时的量化兜底，v6.0.2b 优化后）
```
avg<30 或 回撤>30% 或 Sharpe<-0.5        → SELL  清仓
avg<55 或 Sharpe<0:
    ├─ 若 回撤已释放(当前<50%最大) 且 趋势向上/金叉 → HOLD  (免误减仓 ★新)
    └─ 否则                                       → REDUCE 减仓
avg>75 且 Sharpe>1.0 且 趋势向上:
    ├─ 波动率>60%  → 观望(不加)                    (防过热 ★新)
    └─ 否则        → ADD 增持
MACD死叉 或 趋势向下                              → WATCH 观望(触发条件减仓)
其他混合信号                                      → HOLD
```
> v6.0.2b 修复: 原矩阵对 Sharpe<0 一律减仓，A股基金 Sharpe 普遍<1 导致
> 拥堵时全仓误砍（id=19 四只全 reduce 的教训）。增加"回撤已释放+趋势向好→hold"豁免。

---

## 七、荐基（Screener）设计

- **六因子打分** + 权重重归一化
- **风格归因**: 通过指数相关性判断基金风格（消费/科技/宽基...）
- **冗余惩罚**: 与现有持仓相关性过高的候选降权（避免重复配置）
- **分批净值处理**: 内存峰值 <200MB（适配 3.6G RAM 环境）
- **免责**: 所有推荐带"非投资建议" + 置信度

---

## 八、API 端点（决策类）

| 端点 | 功能 |
|------|------|
| `POST /api/advisor/recommend/timing` | 择时信号（传 fund_code → 买/卖/观/避 + 置信度 + 风控门）|
| `POST /api/advisor/recommend/screen` | 荐基（传 candidates → 打分排序 + 风格标签）|
| `POST /api/analyze` | 手动触发全量分析（可传 push_email/model/force）|
| `GET /api/advisor/reports` | 历史报告列表（分页元数据）|
| `GET /api/advisor/reports/{id}` | 报告详情（完整 JSON）|

> 荐基端点默认不带 LLM 解读（`with_ai_explanation=false`），防 ds-flash 高峰 529。

---

## 九、每日邮件幂等锁（v6.0.1 修复重复邮件）

**根因**: cron `timeoutSeconds=180` << 分析耗时 ~30min → curl 被超时 → cron 重试 → 4并发 → 4封邮件

**方案A（DB 锁）**: `email_send_record` 表 + `report_date` DATE 唯一约束
- `AdvisorJob.run()` 每日幂等：已发今天则 `skipped`，`force` 参数绕锁
- DB 层面兜底并发竞争

**方案B（cron 超时）**: `timeoutSeconds` 180 → 2400（40min，覆盖最长分析）

---

## 十、运维要点

### 服务
| 服务 | systemd | 端口 | 状态 |
|------|---------|------|------|
| backend | fund-advisor-backend.service | :8200 | active |
| frontend | fund-advisor-frontend.service | :8201 | active |
| NewAPI | Docker | :8443 | active |
| cron | FundAdvisor daily analysis push | 工作日 09:00 | nextRun 周一 |

### 重启
```bash
systemctl restart fund-advisor-backend.service
# 若正跑分析, uvicorn 会优雅等连接关闭(可能卡 deactivating 数分钟), 不强杀
```

### 关键脚本
```bash
cd /root/.openclaw/workspace/fund-advisor
.venv/bin/python -c "from backend.database import SessionLocal; ..."  # DB 操作
```

### 引擎改动即时生效
fund-advisor 通过 `sys.path` 引用 fund-analyzer/engine，**改引擎源码后下次分析自动生效**（无需重启/重部署）。

---

## 十一、近期版本记录

| 版本 | commit | 内容 |
|------|--------|------|
| v6.0 | `774a9e2` | RFC-010 荐基+择时部署上线 |
| v6.0.1 | `d940981` | 修复每日重复邮件（幂等锁）|
| v6.0.2 | `8a7cdd1` | 分析提速 + 规避不稳定模型（nano-9b 主力）|
| v6.0.2b | `ed9dc27` | 超时平衡 45s/60s（fund-advisor）|
| — | `e66dfde` | fallback_debate 免误减仓（fund-analyzer）|

---

## 十二、已知限制

1. **NIM 上游不稳定**: 时好时坏，45s 上下剧烈波动，随机让不同环节撞拥堵
   （曾导致 id=20 组合总评缺失）。当前靠 45s 超时 + fallback 链 + 幂等兜底缓解。
2. **ds-flash 完全不可用**: 已彻底绕开，仅作最后兜底。
3. **`email_send_record` 空闲时 0 行**: 只有 cron 邮件路径写记录，手动 analyze 不走。
4. **公网**: 前端 8201 公网可达（1.15.172.64:8201），后端 8200 仅内网（前端 proxy 转发）。

---

## 附: 决策文档索引（docs/）
- RFC-005 多模型辩论 · RFC-006 分析质量(决策矩阵)
- RFC-006b fallback_debate 免误减仓
- RFC-007 择时 · RFC-008 荐基 · RFC-009 四位一体架构 · RFC-010 部署

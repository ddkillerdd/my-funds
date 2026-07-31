# RFC-010: fund-analyzer 引擎部署到 fund-advisor（荐基/择时/基准）

> **状态**: 提案（文档先行，待审阅）
> **日期**: 2026-07-31
> **作者**: AAA
> **前置**: fund-analyzer `engine/{timing,market_data,screener,screen_runner}.py` 已落地并经 99 测试验证
> **目标**: 把 fund-analyzer 新增的「入场择时 / 荐基 / 市场基准」三项能力，通过 fund-advisor 的 FastAPI 层暴露给前端，不破坏现有 v3 分析链路。
> **非目标**: 不做持仓分析改造（现有 analyze 链路保持不动）；不引 akshare；不改数据库 schema（除非文档明确）。

---

## 一、背景与现状

fund-advisor 的 `AdvisorService` 通过 `sys.path.insert(0, "/root/.openclaw/workspace/fund-analyzer")` 直接 import fund-analyzer 的 `engine` 包。因此 `engine/timing.py`、`engine/market_data.py`、`engine/screener.py`、`engine/screen_runner.py` **当前已经可以被 advisor 后端 import**，无需任何安装/打包。

现有 API 只有 4 类（见 `backend/api/advisor.py`）：
```
POST /api/advisor/analyze      # 持仓 AI 分析（v3 默认）
GET  /api/advisor/report       # 最新报告
GET  /api/advisor/reports      # 报告列表
GET  /api/advisor/report/{id}  # 单报告
GET  /api/advisor/status       # 服务状态
```

**空缺**：没有「入场时机推荐」「荐基打分」两个能力，也从未把「市场基准（沪深300 等）」注入到持仓分析的事实卡里（fund-analyzer 已支持 `portfolio_input.benchmark_nav_history` + `peer_benchmark`）。

---

## 二、部署方案总览

新增 **2 个 API 端点** + **1 处现有链路增强**（可选），全部在现有 FastAPI 架构内：

| # | 端点 | 能力 | 对应引擎 | 复杂度 |
|---|------|------|----------|--------|
| 1 | `POST /api/advisor/recommend/timing` | 对指定基金给出入场择时评分/操作建议 | `engine/timing.compute_entry_recommendation` | 低 |
| 2 | `POST /api/advisor/recommend/screen` | 对候选基金池打分排序（荐基） | `engine.screen_runner.run_screener` | 中 |
| 3 | `analyze` 增强（可选） | 注入沪深300基准对比到事实卡 | `engine.market_data` + `qi.peer_benchmark` | 低 |

前端配套：新增 2 个视图/卡片（择时卡片 + 荐基结果表），复用现有 API client 模式。

---

## 三、数据流与内存约束（服务器现实）

服务器：3.6GB RAM / **0 swap** / 24GB 磁盘 / 东财为唯一数据源。

- 所有抓取仍是 **按需拉取**（无常驻爬虫轮询）。
- 荐基候选**逐个**处理：抓一只 fund → compute_all → 释放原始 nav（`navs.clear()` + 拷贝给 `qi._navs`）→ 下一只。峰值内存 < 200MB。
- `engine/market_data.py` 自带 `data_cache/` 磁盘缓存，同一天多次推荐不会重复抓东财（避免封 IP）。
- **候选池上限**：推荐一次 ≤ 10 只（RFC-008 默认 top_n=10；避免长时间抓取 + 高内存）。如需更大池，分批。
- **推荐运行在请求内置卡一个超时**（FastAPI 同步端点默认阻塞线程，见 §六 风险），单次荐基建议后台任务化或设置 run_screener 内部 deadline。

---

## 四、端点设计

### 4.1 `POST /api/advisor/recommend/timing`

输入（JSON body）：
```jsonc
{
  "fund_code": "161725",      // 必填
  "fund_name": "招商中证白酒指数(LOF)A",  // 可选，缺省自动从东财取
  "playbook": "value"          // 可选：策略风格 value|trend|balanced，默认 auto
}
```

流程：
1. 用 `engine.screen_runner.fetch_fund_nav_full` 拉取该基金 NAV 历史（pingzhongdata 单请求，~2700 天）。
2. 若无估值数据，用 `market_data.nav_based_valuation_percentile` 计算 NAV 估值分位，注入 `qi._valuation_percentile`。
3. 调 `timing.compute_entry_recommendation(qi, ...)`。
4. 返回 `EntryRecommendation` 序列化结果。

响应（`EntryRecommendation` 字段）：
```jsonc
{
  "fund_code": "161725",
  "fund_name": "招商中证白酒指数(LOF)A",
  "recommendation": "staged_entry",      // avoid | wait | staged_entry | buy_now | dca
  "confidence_pct": 68,
  "timing_factors": [{"name":"technical_score","value":42}, {"name":"drawdown_score","value":85}],
  "risk_gate_status": "passed",          // passed | blocked(原因)
  "suggested_dca": {"months":12,"per_installment_pct":8},
  "notes": ["净值历史2721天", "估值分位7.6%(低估)"],
  "disclaimer_note": "仅供参考，不构成投资建议"
}
```

Pydantic schema：新增 `backend/schemas/advisor_recommend.py`（`TimingRequest`/`TimingResponse`）。

### 4.2 `POST /api/advisor/recommend/screen`

输入（JSON body）：
```jsonc
{
  "candidates": [ {"fund_code":"161725","fund_name":"招商中证白酒指数(LOF)A"}, {"fund_code":"110022",...} ],
  "budget_pct": 10,             // 可选，单标的基础配比
  "top_n": 5,                   // 可选，最多返回
  "portfolio_holdings_info": "当前重仓易方达消费(30%)",  // 可选，供LLM解读上下文
  "with_ai_explanation": true   // 可选，是否追加LLM一句解读
}
```

流程：
1. 若未传 `portfolio_navs`，则读取当前 DB 持仓的 NAV 历史作为分散化参照：`NavService.get_held_fund_codes()` → 逐个 `get_nav_history(code, days=250)`（现有方法，无需改动）。
2. 拉取各候选 NAV + 详情（分批，≤10 只）。
3. 拉取 5 大风格指数（`batch_fetch_indexes`）。
4. `run_screener` → 排序评分。
5. 若 `with_ai_explanation`，用 `run_screener_with_explanation` 追加 LLM 后置解读（只解读不评分）。

响应（`ScreenerResult` 序列化）：
```jsonc
{
  "candidates_scanned": 3,
  "portfolio_context": {"top1_pct":30},
  "recommendations": [
    {
      "fund_code":"110022","fund_name":"易方达消费行业股票",
      "total_score":35.4,"style_tag":"创业板指",
      "correlation_with_portfolio":0.12,"suggested_ratio_pct":10,
      "factor_scores":[{"factor":"momentum","score":13,"evidence":"..."}],
      "ai_explanation":"...",
      "disclaimer_note":"仅供参考，不构成投资建议"
    }
  ],
  "data_quality":"good",
  "notes":[]
}
```

---

## 五、现有链路增强（可选，默认建议做）

### 5.1 `analyze` 注入沪深300基准（事实卡上下文）

现有 `AdvisorService._build_portfolio_input()` 不填 `benchmark_history`。增强：
- 在 `_analyze_v3()` 里拉取沪深300指数序列（`market_data.fetch_index_nav`），填入 `portfolio_input.benchmark_nav_history`。
- fund-analyzer 的 `analyze()` 已支持对该字段自动 `compute_peer_benchmark`，让事实卡出现「本基金波动 42% vs 大盘 18%（2.3x）」这类上下文。
- **风险**：多一次东财抓取 + analyze 已很慢（830s/LLM 27次），建议该增强做成**开关**（默认关，避免拖慢主链路、且 ds-flash 高峰 overload 时雪上加霜）。推荐：放在 `recommend/timing` 单基金场景用，而不是全局 analyze。

> **建议结论**：5.1 默认**不做到全局 analyze**，仅作为 `recommend/timing` 的可选补充。第一个版本先落 4.1 + 4.2。

---

## 六、技术风险与对策

| 风险 | 评估 | 对策 |
|------|------|------|
| 同步端点阻塞 worker 线程 | 抓取+量化可能 5-20s | FastAPI 同步 def 跑在线程池（可接受）；或用 `def` + `run_in_executor`；前端 loading 态 |
| 多次荐基触发东财反爬 | 高 | `data_cache/` 缓存 + 候选池 ≤10 + 避免高频重复调用 |
| ds-flash 高峰 529 overload | 高（荐基解读用 LLM 时） | `with_ai_explanation` 默认 false；LLM 只做解读灾难性低（评分已在 Python 完成） |
| 候选基金 nav 不足 | 低 | `build_candidates_indicators` 已跳过 <30 天的 |
| 内存峰值 | 低 | 逐个处理 + 释放；候选 ≤10 |
| 域名/端口冲突 | 无 | 全部复用现有 :8200 FastAPI |

---

## 七、实施步骤（文档先行通过后执行）

1. **Pydantic schema**：`backend/schemas/advisor_recommend.py`（Timing/Screen 请求响应）。
2. **Service 桥接**：`backend/services/recommend_service.py`：
   - `get_timing(fund_code, playbook)` → 调 `timing`
   - `run_screen(candidates, budget, top_n, with_ai)` → 调 `screen_runner`
   - 复用 `NavService.get_held_fund_codes()` + `get_nav_history(code, days=250)` 取当前持仓 NAV 作分散参照。
3. **API 路由**：`backend/api/recommend.py`（2 个端点），并在 `api/router.py` 注册 `/api/advisor/recommend`（可并入 advisor.py 或独立文件，倾向独立 `recommend.py` 保持整洁）。
4. **前端**：`frontend/src/views/` 新增 `RecommendView.vue`（择时输入 + 荐基候选输入 → 结果表），router 注册路由，复用 `frontend/src/api` client。
5. **测试**：`backend/tests/` 补齐 recommend_service 单测（mock 东财客户端）。
6. **DEVLOG/README** 更新 + commit。

## 八、验收标准

- [ ] `POST /api/advisor/recommend/timing` 对 161725 返回结构化择时（白酒应 → staged/DCA，因低估）。
- [ ] `POST /api/advisor/recommend/screen` 对 [161725, 110022, 005827] 返回排序（消费三只都应低分，反映当前回撤，诚实输出）。
- [ ] 内存峰值 < 200MB（推荐期间 `free -m` 观察可用内存）。
- [ ] 现有 `POST /api/advisor/analyze` 行为不变（回归）。
- [ ] 99 个 fund-analyzer 测试 + 新增 recommend_service 测试全绿。

---

## 九、不做的事（明确边界）

- 不引入 akshare / 任何重依赖。
- 不改 AnalyzeReport / AdvisorReport 的数据库 schema。
- 不把「五因子/择时评分」交给 LLM 生成（只解读不评分，防幻觉）。
- 第一个版本不把基准注入全局 analyze（见 §5.1 结论）。

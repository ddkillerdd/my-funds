# Changelog

> 版本变更摘要。详细开发日志见 `DEVLOG.md`。

## [6.4] - 2026-08-01 — run-advisor 落库 + 量化组合诊断

### Fixed
- **定时/手动 run-advisor 不落库**：`POST /api/scheduler/run-advisor` 原先只分析+发邮件，报告不进 `advisor_report`，前端永远看不到定时分析结果（只能看邮件）。新增 `AdvisorJob._persist_report()`：写报告 + RFC-012 回测快照 + 按 `MAX_REPORTS=30` 清理旧报告。定时/手动分析现在都会落库、前端可回溯、计入回测命中率。
- **组合诊断偶发空白**：portfolio 阶段 NIM(omni-30b/nano-9b) 多次超时/残缺返回时，组合诊断字段会静默变空（连"无法评估"都消失），前端整块空白。

### Changed
- **组合诊断改为纯量化计算**（B 方案）：`_portfolio_synthesis` 去掉全部 LLM 调用，改由 `PortfolioGroundTruth`（集中度/有效前沿/盈亏/相关性）确定性生成——整体健康分按集中度+前沿偏离+盈亏+数据质量加权扣分 → `health_label`；集中度风险输出真实 HHI/前1/前3 占比；调仓建议由最优 Sharpe 权重量化生成；strength/weakness 用量化事实模板。彻底杜绝 NIM 超时导致的空白/摆荡，零 LLM 依赖（符合"LLM 只解读不评分"，组合解读进一步量化）。

### Added
- `AdvisorJob.report_id` 实例字段（本次运行落库的报告 id），调用方/cron 可直接获取。

### Verified
- 全引擎 123 测试通过（含 money_fund/序列化回归）。
- 量化组合诊断单测：`overall_health_score=72/均衡`、`concentration_risk=HHI 0.33+前3占75.2%`、`rebalance_direction=适度再平衡`、rebalance_suggestions 4 条、strength/weakness 均量化生成。
- 端到端 run-advisor：id=25 由 scheduler 正确落库 + `record_advice: wrote 4 advices`。

## [6.3] - 2026-08-01 — 动作确定性收敛（RFC-013）

### Changed
- **动作决策全量化，LLM 只解读**：新增 `fund-analyzer/engine/decision.py`（`score_views_quant` / `detect_regime` / `deterministic_action` / `merge_with_llm_explanation` / `summarize_regime`），同一量化事实产出 100% 可复现的动作，消除同日多报告动作摆荡。
- **Regime-aware 牛熊感知**（FINSABER 实证驱动）：牛市不再误砍优质资产（000311 不再被误减仓）；熊市严格止损（负 sharpe 基金 reduce），避免死扛深亏。
- `analyzer.py`：`_analyze_4_views` 四视角分数改量化计算（LLM 仅作 `llm_interpretive` 展示）；`_debate_synthesis` 动作走 `deterministic_action` + merge，LLM 观点降级为 `note` 附注。

### Added
- 报告字段：`decision_source="quant_primary"`、`debate.action.note`（LLM 冲突附注）、`regime`。
- 测试 `tests/test_decision.py`（19 个）幂等/regime 三态/六档边界/冲突合并。

### Fixed
- **同日多报告动作矛盾**（id=19/20/21 vs id=22）：同持仓量化事实一致但 LLM 打分随机摆荡 ±20 分导致动作反复，现由量化锁定。

### Verified
- 全引擎 120 测试通过（101 原 + 19 新）。
- 真实报告 id=22 四基金动作全一致（watch/hold/hold/hold），全部 `quant_primary`；161725 冲突附注生效。

## [6.2] - 2026-07-31 — 建议回测 + 自适应在线学习（RFC-012）

### Added
- **建议回测** `fund-analyzer/engine/backtest.py`：相对沪深300 判定 REDUCE/INCREASE 命中，HOLD/WATCH 中性。
- **自适应在线学习** `engine/learning.py`：贝叶斯收缩校准置信度（0.40-0.95），`advice_snapshot` + `factor_hit_rate` 表。
- `BacktestService` + API `/api/backtest/stats|validate|adapt`；报告生成后自动记录快照，daily scheduler 每日验证 + 10 天适应。
- 前端 AdvisorView 回测命中率展示卡。

### Notes
- `validate_due` 用 `fund_nav_history` 实时净值回测，报告即便没存 NAV 也可回测。

## [6.1] - 2026-07-31 — 持仓操作记录（RFC-011）

### Added
- **持仓增/减仓** `POST /holdings/{id}/change` + 前端 HoldingsView 按钮/对话框。
- 决策：减仓到 0 自动清仓；按实际人民币金额输入；加仓重算平均成本（B 方案，为盈利精确服务）。
- 文档 `fund-advisor/docs/RFC-011-holding-change-ops.md`。

## [6.0.1] - 2026-07-31 — 修复每日重复邮件

### Fixed
- **每日邮件幂等锁**：新增 `email_send_record` 表（`report_date` 唯一），`AdvisorJob` 每天只发一封分析邮件，重复触发直接跳过；`force=true` 可强制重发
- **cron 超时误判**：`FundAdvisor daily analysis push` timeout 180s→2400s，避免 30min 分析被误判超时导致 cron 重试发多封

### Notes
- 根因：cron 180s 超时 < 分析 30min → curl 被重试 → 4 个并发 AdvisorJob → 4 封同样邮件

## [6.0.0] - 2026-07-31 — 荐基 + 择时 上线（RFC-010）

### Added
- **入场择时** `POST /api/advisor/recommend/timing` — 纯量化（技术/趋势/回撤/估值 4 因子 + 硬风险门 + 定投建议），无 LLM
- **荐基打分** `POST /api/advisor/recommend/screen` — 六因子（动量/质量/回撤/分散/规模/估值）排序 + 风格归因 + 建议配比；可选 LLM 后置解读（只解读不评分）
- **前端**「荐基 & 择时」视图 `/recommend`（`RecommendView.vue`）+ 侧边栏入口
- 桥接 `backend/services/recommend_service.py` 复用 `NavService` 持仓 NAV 作分散化参照

### Notes
- 荐基候选 ≤10 只，逐个处理，内存峰值 <200MB（3.6G 服务器现实）
- AI 解读默认关闭，避免 ds-flash 高峰 529 拖慢评分主链路

## [3.0.0] - 2026-07-30 — FundAnalyzer 独立引擎 + 集成上线

### Added
- **FundAnalyzer** — 独立投资分析引擎包 (`fund-analyzer/`)，零耦合于 FundAdvisor
  - `engine/models.py` — 32 个 dataclass 定义完整 I/O 协议
  - `engine/quant.py` — 32 个量化指标 (趋势/MACD/动量/风险/收益/效率/基准)，纯 Python 计算，零 LLM 参与
  - `engine/portfolio_quant.py` — 相关性矩阵 / HHI 集中度 / 5000 次模拟有效前沿
  - `engine/prompts.py` — 7 个 Agent 提示模板 (Trend/Risk/Value/Tech/辩论/组合/交叉验证)
  - `engine/llm_client.py` — 模型回退链 (nemotron → deepseek) + JSON 解析 + 降级函数
  - `engine/analyzer.py` — 5 步流水线协调器 (量化→4视图→辩论→组合诊断→交叉验证)
  - 57 个单元测试全部通过
- **4 视图分析** — 每只基金由 4 个独立 Agent 从不同角度诊断 (Trend/Risk/Value/Technology)
- **辩论机制** — 4 视图输出汇总给第 5 个 Agent 寻找矛盾、裁决分歧、计算健康度
- **有效前沿** — 组合层面 5000 次 Monte Carlo 模拟寻找最优权重
- **交叉验证** — 审计整份报告发现矛盾/幻觉/遗漏/置信度虚高

### Changed
- **advisor_service.py** 重写为 FundAnalyzer 适配层 (~200 行核心代码)
  - 默认引擎: v3 (FundAnalyzer)，可通过 `?engine=v2` 降级
  - DB 数据 → PortfolioInput 适配器
  - AnalysisReport → API JSON 转换器 (完全兼容前端)
- **API `/analyze`** 默认走 FundAnalyzer，`?engine=v2` 回退旧引擎

### Fixed
- nemotron 推理模型双引号包裹 JSON → 递归解析
- nemotron content=null 时降级读取 reasoning 字段
- max_tokens 2048→4096 给推理模型留足空间
- JSON 边界多候选扫描 → 选 dict 最大者
- 3 只基金名称从 "基金XXXXXX" 修复为真实名称

### Performance
- 4 只基金完整分析: ~775s (22 次 LLM 调用，0 次失败/降级)
- 模型: nemotron-nano-9b-v2 (1-2s/次)，deepseek-v4-flash 备用

### Docs
- docs/RFC-004-quantitative-analysis-engine.md — 量化引擎设计文档
- docs/report-persistence.md — 报告持久化方案
- fund-analyzer/README.md + DESIGN.md — 独立引擎文档

---

## [2.0.0] — 2026-07-30

### Added
- 多模型协作分析架构 (RFC-003) — 4 层分析引擎
- Step1 逐基金分析 / Step2 组合诊断 / Step3 反方验证 / Step3b 紧急表决
- `facts_computer.py` — 纯 Python 预计算客观数据

### Changed
- 温度降为 0/0.1 (消除随机性)
- 遵守 1.6s 间隔 + 120s 超时 (NVIDIA NIM 限制)

### Archived
- Step1-3 的 LLM 调用逻辑已被 v3 完全替代
- `facts_computer.py` 功能由 fund-analyzer/engine/quant.py 覆盖

---

## [1.4.0] - 2026-07-30

### Added
- AI 顾问报告持久化 — 不刷新丢失
- `advisor_report` 表 / GET 接口列表
- 前端左侧历史侧栏 + 分页

### Changed
- 时间统一转为北京时间 (CST)
- systemd 保活前后端

---

## [1.3.0] - 2026-07-30

### Added
- 快捷导入 (RFC-002): 基金代码 + 持有金额 → 自动反算份额

---

## [1.1.0] - 2026-07-29

### Added
- 回退模型链: step-3.7 → nemotron-nano-9b → minimax-m3

---

## [1.0.x] — 2026-07-29

### Added
- Phase 0: 环境适配 (Python 3.12 + Docker MySQL + CORS)
- Phase 1: Bug 修复 (货币基金净值/收益一致性/资产偏差)
- Phase 1.2: 手动持仓录入
- Phase 2: AI 决策引擎 + 四大分析维度
- Phase 3: 自动化推送 (工作日 09:00)

### Fixed
- 货币基金万份收益错误
- NEWAPI 配置被 SMTP 覆盖
- NVIDIA NIM 推理模型 content=null

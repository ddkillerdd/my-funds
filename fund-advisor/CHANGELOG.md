# Changelog

> 版本变更摘要。详细开发日志见 `DEVLOG.md`。

## [Unreleased] - 2026-09-05 — 持仓正确性最终准入第一阶段收口

### Verified
- 完成 A-D 持仓正确性功能的本地差异分组复核；未修改生产实现，未处理两个受保护的 `fund-analyzer/tests` 文件。
- 变更范围内 22 个 Python 文件 AST 解析通过，`git diff --check` 通过，前端纯逻辑测试 7/7 通过。
- 指定 Node/npm 生产构建在允许启动 esbuild 子进程的执行环境中通过（Vite 6.4.1，2103 个模块，10.67 秒，仅有大于 500 kB chunk 警告）；此前受限沙箱的 `spawn EPERM` 不作为代码/发布阻塞。后端与分析引擎 pytest 因 Bundled Python 缺少 `pytest` 各退出 1，尚未形成完整 Python 通过证据。

### Release boundary
- 四组本地提交已按白名单完成，当前等待独立 GitHub 推送确认；staging、生产、服务器、OpenClaw、systemd、cron 和数据库均未操作。
- 在 Python 全量测试、迁移和隔离 staging 验收完成前，不宣称生产可发布。

### Staging and regression evidence
- c5444b63 staging 镜像构建成功；合成 MySQL 曾健康运行，空库迁移至 `b1c2d3e4f5a6`，旧 schema `a1b2c3d4e5f6` 升级至 head 成功。
- 初次后端 68/4、分析引擎 163/2（后者为两个已登记保护失败）；修复后定向测试 4/4、后端完整测试 72/72 通过，均带 `-p no:cacheprovider`。
- c544 staging MySQL 已停止并保留 runtime、镜像、网络、卷和合成数据；生产与旧 staging 未改，待新修复 SHA 重建 staging 后继续验收。

## [7.1] - 2026-08-03 — RFC-020 长线分析增强（Phase 1 + Phase 2）

### Added（Phase 1）
- 自适应 WFA NaN 修复：quant.py 三处 `np.std(ddof=1)` 自由度=0→NaN 问题，加 `len>1` guard；adaptive_optimizer 加 `MIN_NAVS_FOR_WFA=60` 剔除短历史基金
- 总资金动态配置：`app_config` key-value 表 + `GET/PUT /api/config/total-capital`，前端可调，作为绝对金额定价基准
- 操作金额闭环：报告后端本有 `action_amount`（正加负减），前端操作建议卡片补渲染
- 决策推送 cron 改 13:30（原 09:00），留 15:00 前决策窗口

### Added（Phase 2）
- 短线择时 `intraday.py`：腾讯行情（实时涨跌% + 5日线偏离）→ execution_advice，只出信号不改金额，报告新增 `intraday_view`
- 市场基准对比 `index_bindings.py`：沪深300 500 天注入 `benchmark_nav_history`，报告新增 `benchmark.attached`，修复 peer_benchmark 挂载路径（fd.ground_truth）
- 实际操作记录 `trade_execution`：表 + `/api/trade-execution/*` + 前端"我实际"下拉，记录建议 vs 实际偏差供校准

### Changed
- 行情数据源从 eastmoney 改为腾讯：eastmoney 对 Python httpx 做 TLS 指纹拦截（实时 push2/历史 push2his 都封，curl 却通），腾讯 gtimg.cn httpx 全通且稳定（覆盖 A 股指数 + 美股纳指）
- 调度：`FundAdvisor 收盘前决策推送` = `30 13 * * 1-5`

### Verified
- 活 HTTP 端点真实分析：success=True, analysis_ok=True, 21 次 deepseek 0 失败非降级, 414s(6.9min)
- 4 条 actions 带金额、intraday_view 4 基金（科创50 -5.08% 正确判"较佳买点"）、benchmark attached=true
- 实际操作记录实测：建议“减仓 -¥27513” + 用户回填"照做" 正确对应存储

## [7.0] - 2026-08-01 — RFC-014 盈利导向决策引擎 v2（Signal→Position→Risk 三层闭环）

> 设计文档：`fund-analyzer/docs/RFC-014-position-decision-engine.md`（重构唯一准绳，不受旧 RFC 约束）。
> 唯一目标：为盈利服务，决策全量化、确定性、可回测。

### Added（决策引擎三层闭环）
- **L1 方向信号** `compute_direction`：动量(12月收益·0.5) + 均线排列(MA20/60·0.3) + RSI 修正(0.2) → `direction_score`∈[-1,1]
- **L2 仓位映射** `build_position_action`：波动率目标 vol targeting（`target = base × (target_vol ÷ realized_vol)`，默认 target_vol=15%）→ 每只基金目标仓位%
- **L3 风控层**（硬约束，优先级降序）：R1 回撤>25%清仓 / R2 回撤15-25%重仓减半 / R3 年化波动>60%压到30% / R4 单基目标>50%压到50% / R5 熊市防御≤30% / R6 换手触发带5pp防摩擦
- **唯一权威动作结构 `PositionAction`**：五档 `buy/increase/hold/reduce/sell` + `target_weight%` + `regime` + `decision_source=quant_primary`，全量化幂等零 LLM
- `tests/test_position.py` 11 用例（波动率目标/回撤止损/熊市防御/集中度/换手带/幂等/零LLM/动作-仓位自洽）

### Changed
- `_debate_synthesis` 动作源由 `deterministic_action` 升级为 `build_position_action`（`qi.mv_ratio` 作当前权重）
- `merge_with_llm_explanation` RFC-014 优先：LLM 只附解读到 `reason`，永不改动作字段，冲突仅 note
- `advisor_service._extract_actions` **单一权威重构**：只读每基 `debate_summary.action`，不再用 `rebalance_suggestions` 覆盖 → 根治历史「actions vs holdings_health 互相矛盾」
- `holdings_health[].suggestion` 统一读 PositionAction + 新增 `action_label`/`target_weight_pct`
- `normalize_action` 兼容 PositionAction（新字段保留，老字段 `type/change_pct` 补全为超集，历史报告不破）
- 前端 AdvisorView 三视图统一读 `action_label` + 目标仓位%，旧报告无新字段时兼容兜底

### 验证
- 全引擎 137 测试通过（126 原 + 11 新）
- 前端 `vite build` 通过
- 后端重启 active，:8200 HTTP 200
- 离线映射验证：id=23/25/26 动作统一为 per-fund watch/hold/hold/hold（id=26 原先被 rebalance 污染的 increase/decrease 已纠正）

## [6.4.1] - 2026-08-01 — 量化组合诊断 rebalance 阈值门控

### Fixed
- **量化组合诊断意外覆盖 per-fund 决策（回归）**：量化版 `_portfolio_synthesis` 总是生成 4 只基金 rebalance_suggestions，被后端无条件当顶层 `actions`（advisor_service.py），导致 id=26 动作全变 `source=rebalance`、`regime=None`，覆盖 RFC-013 的 `quant_primary` 决策。
- 修复：`rebalance_suggestions` **仅当组合偏离有效前沿 >3% 才生成**，否则返回空列表 → 让 per-fund 的 `quant_primary`+`regime` 决策主导（与 id=23/25 行为一致）。`rebalance_direction` 阈值统一为 >3%，清理死代码 `optimal_vs_current`。

### Added
- 组合诊断门控测试 3 个（接近前沿不生成建议 / 显著偏离生成建议 / 量化标签非空），全引擎 126 测试通过。

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

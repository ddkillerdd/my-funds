# Changelog

> 版本变更摘要。详细开发日志见 `DEVLOG.md`。

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

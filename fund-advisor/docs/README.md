# fund-advisor/docs — 应用层文档导航

> 本目录存放 **fund-advisor Web 应用层** 的专属文档(部署/运维/调度)。分析引擎的 RFC 统一在 `fund-analyzer/docs/`。

## 本目录 (应用层)

| 文档 | 说明 |
|------|------|
| `RFC-010-deploy-recommend-engines.md` | 推荐引擎部署 |
| `RFC-011-holding-change-ops.md` | 持仓变动操作 |
| `RFC-012-backtest-adaptive-learning.md` | 建议回测 + 自适应学习 |
| `RFC-014-position-decision-engine.md` | **软链** → 指向 `../../fund-analyzer/docs/RFC-014`(决策引擎为双项目共用,唯一权威在 fund-analyzer) |
| `RFC-017-adaptive-optimization.md` | 自适应优化(WFA 参数自学习,半自动)
| `RFC-018-ai-investment-center-调研.md` | **AI投顾长期投资方案中心 · 调研** |
| `RFC-018-ai-investment-center-架构.md` | AI投顾长期投资方案中心 · 架构设计 |
| `RFC-018-ai-investment-center-详细设计.md` | AI投顾长期投资方案中心 · 详细设计 |
| `RFC-018-ai-investment-center-开发计划.md` | AI投顾长期投资方案中心 · 开发计划 |

## 引擎层文档 (fund-analyzer)

分析/荐基/择时/决策/模拟的 RFC 全部在 `fund-analyzer/docs/`,见 [fund-analyzer/README.md](../../fund-analyzer/README.md) 文档索引:
- RFC-005 多模型辩论 / RFC-006 分析质量 / RFC-007 择时 / RFC-008 荐基 / RFC-009 架构总纲 / RFC-013 动作确定性 / RFC-014 决策引擎 / RFC-016 组合回测

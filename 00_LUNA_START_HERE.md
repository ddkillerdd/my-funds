# Luna 从这里开始

开始修改代码前，按顺序完整阅读：

1. `AGENTS.md` 及当前目录范围内其他适用指令。
2. `docs/development/LOCAL_DEVELOPMENT_ENVIRONMENT.md`：已验证的本地环境、命令、数据边界和生产漂移风险。
3. `DEVELOPMENT_PLAN_PROFITABILITY.md`：盈利链路问题、修复计划、测试、部署与回滚。
4. `DEVELOPMENT_DECISIONS.md`：用户确认的 20% 最大回撤、staging 和手工交易同步规则。
5. `DEVELOPMENT_PORTFOLIO_SCALING.md`：未来新增基金、追加资金和多基金组合兼容规则。
6. `docs/development/P0_ACCEPTANCE_REPORT.md`：P0 验收证据、Git 风险和 Luna 下一任务边界。
7. `LUNA_HANDOFF.md`：当前完成状态和后续接手检查清单。

当前 P0 功能验收已通过：分析引擎 165 项、后端 5 项测试通过；但 Git 发布包尚未验收，当前改动仍未形成明确提交 SHA，也未部署服务器。Luna 的下一任务是提交前收口，不得直接进入部署，不得因为当前只有约 1.48 元和一只基金而硬编码金额或基金数量，也不得把策略参数调整混入正确性修复。

系统只提供建议。只有用户确认实际操作及平台成交信息后才同步持仓；用户未操作时，持仓保持原样。

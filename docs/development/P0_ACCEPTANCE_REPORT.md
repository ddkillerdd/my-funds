# P0 跨层正确性修复验收报告

> 验收日期：2026-09-01
> 仓库：`E:\myfund11111`
> 验收范围：最近净值窗口、现金与目标权重、零目标语义、动作映射与命中率
> 数据边界：全部测试使用合成数据和伪造 Session，未读取服务器真实持仓或秘密

## 1. 验收结论

本轮 P0 功能验收通过。四组已确认的跨层正确性问题均已有本地实现和回归测试，分析引擎与后端完整测试通过，未调整策略参数，未连接或部署服务器。

验收状态分为三层：

| 层级 | 状态 | 说明 |
| --- | --- | --- |
| P0 功能正确性 | 通过 | 170 项 Python 测试通过，最近一次前端生产构建通过 |
| Git 发布包 | 未通过 | 工作区混有既有改动，尚未完成差异分类、分批提交和明确提交 SHA |
| 服务器发布 | 未执行 | 未做服务器写入、数据库迁移、服务重启或生产部署 |

因此可以切换 Luna 执行“提交前收口”，但不得直接进入服务器部署。P1 代码开发应在 P0 差异边界确认、形成提交并复跑统一检查之后开始。

## 2. 当前 Git 基线

- 分支：`main`。
- 当前提交：`afc19e9`。
- `HEAD`、`origin/main` 和 `origin/HEAD` 指向同一提交。
- 当前有 30 个已跟踪文件发生变化、25 个未跟踪文件（包含本验收报告）。
- 已跟踪差异为 359 行新增、114 行删除；该统计不包含未跟踪文件。
- 工作区中的环境、运维、文档和 P0 代码改动来自连续开发过程，不能假定全部属于同一个提交。

不得使用 `git reset --hard`、`git checkout --` 或覆盖式同步清理工作区。Luna 必须先按任务来源和功能边界整理差异，再提出提交方案。

## 3. 四组 P0 验收矩阵

### 3.1 最近净值窗口与建议时点净值

验收结果：通过。

- 后端先按净值日期倒序查询最新 N 条，再恢复为时间升序供指标计算。
- 量化结果显式保存最新净值和净值日期。
- API 报告统一输出 `quant.nav` 和 `quant.nav_date`。
- API 与调度器兼容历史 `quant_indicator` 字段，并把建议时点净值写入回测快照。
- 动作提取不再依赖不存在的 `report.quant_map`，也不再读取不存在的 `NavPoint.value`。

主要实现：

- `fund-advisor/backend/services/advisor_service.py`
- `fund-advisor/backend/api/advisor.py`
- `fund-advisor/backend/scheduler/advisor_job.py`
- `fund-analyzer/engine/models.py`
- `fund-analyzer/engine/quant.py`

### 3.2 现金仓位与组合目标权重

验收结果：通过。

- 单基金 25% 目标保留约 75% 现金，不再被归一化为满仓。
- 默认逐基金信号通过显式组合预算协调进入可执行范围。
- 外部注入策略的组合目标权重超过 100% 时直接报错，不静默归一化。
- 每个目标权重必须是有限数值并位于 0 到 1 之间。

主要实现：

- `fund-analyzer/engine/allocation.py`
- `fund-analyzer/engine/simulator.py`
- `fund-analyzer/engine/analyzer.py`

### 3.3 显式零目标与缺失目标

验收结果：通过。

- 显式 `target_weight=0` 表示清仓并转为现金。
- 缺少 `target_weight` 表示没有新的仓位目标，维持现有绝对持仓金额。
- 预热期没有策略信号时维持当前仓位。
- 零目标不再退化为等权满仓。

主要实现：

- `fund-analyzer/engine/allocation.py`
- `fund-analyzer/engine/analyzer.py`
- `fund-analyzer/engine/simulator.py`

### 3.4 动作映射与命中率分母

验收结果：通过。

- `buy`、`increase` 和历史 `add` 统一判定为正向动作。
- `sell`、`reduce` 和历史 `decrease` 统一判定为负向动作。
- `hold`、`watch` 为中性动作，不进入方向命中率分母。
- 命中率分母使用可验证的 `hit + miss`，中性结果单独计数。
- 后端输出方向覆盖率，前端明确显示命中数、方向分母、中性数和待验证数。

主要实现：

- `fund-analyzer/engine/action_mapping.py`
- `fund-analyzer/engine/backtest.py`
- `fund-analyzer/engine/decision.py`
- `fund-analyzer/engine/llm_client.py`
- `fund-advisor/backend/services/backtest_service.py`
- `fund-advisor/backend/schemas/backtest.py`
- `fund-advisor/frontend/src/views/AdvisorView.vue`

## 4. 回归测试证据

### 4.1 分析引擎完整测试

```powershell
# 禁用 pytest 缓存，避免仓库根目录旧缓存 ACL 影响测试结果。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' `
  -m pytest 'E:\myfund11111\fund-analyzer\tests' -q -p no:cacheprovider
```

结果：`165 passed`。

### 4.2 后端服务完整测试

```powershell
# 后端服务测试使用伪造 Session，不连接本地或服务器数据库。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' `
  -m pytest 'E:\myfund11111\fund-advisor\backend\tests' -q -p no:cacheprovider
```

结果：`5 passed`。

### 4.3 P0 专项覆盖

专项测试位于：

- `fund-analyzer/tests/test_p0_profitability_correctness.py`
- `fund-advisor/backend/tests/test_p0_services.py`

覆盖最近 N 条净值窗口、建议时点净值、现金保留、预热期持仓、零目标、缺失目标、超配拒绝、历史动作别名、方向命中率分母和覆盖率。

### 4.4 其他检查

- Python AST：122 个文件通过语法解析。
- `git diff --check`：退出码为 0，仅有 Windows 下 LF/CRLF 转换提示。
- 前端 `package.json` 和 `package-lock.json`：可解析。
- 常见私钥、Token 特征扫描：未发现命中。
- 最近一次前端生产构建：通过，转换 2102 个模块；保留入口包体积大于 500 KB 的既有提示。

## 5. 尚未关闭的风险

### 5.1 统一检查脚本被旧缓存 ACL 阻断

`ops/Invoke-LocalChecks.ps1` 在递归枚举 Python 文件时无法访问 `E:\myfund11111\.pytest_cache`，会在测试开始前因权限拒绝退出。当前通过 `-p no:cacheprovider` 独立运行两套测试可以稳定通过，但统一脚本仍需要在单独任务中改为显式排除缓存目录或使用不会递归进入该目录的文件枚举方式。

不得为了消除提示直接删除未知来源的缓存目录；应先核对 ACL 和目录来源。

### 5.2 工作区不是可发布状态

当前工作区同时包含 P0 代码、环境引导、运维文档和其他既有改动。虽然测试通过，但没有明确提交 SHA，不能作为部署源。

### 5.3 尚未完成 staging 和生产验收

本轮没有核对服务器热修差异、生产数据库版本、备份恢复路径和真实部署运行时。生产数据库和服务不得因本报告被重启或修改。

### 5.4 策略收益尚未验收

P0 通过只说明数据、仓位和统计口径更可信，不代表策略已经证明可以盈利。费用、到账状态、手工成交确认、样本外验证和真实执行归因属于后续阶段。

## 6. Luna 下一步执行范围

Luna 下一任务限定为“提交前收口”，不得顺手改策略参数或部署服务器：

1. 阅读 `AGENTS.md`、`00_LUNA_START_HERE.md`、本报告和 `LUNA_HANDOFF.md`。
2. 执行 `git status --short --branch`、`git diff --check`，审查当前所有未提交差异。
3. 把差异分为 P0 正确性、开发环境/运维、文档和其他既有改动，标明互相重叠的文件。
4. 复核四组 P0 的实现与专项测试，不重复重写。
5. 提出可独立审查的提交拆分方案；未获得用户确认前不提交、不推送。
6. 使用本报告中的无缓存命令复跑两套测试。
7. 汇报可提交文件、遗留风险和是否具备进入 P1 的条件。

可直接发送给 Luna 的指令：

```text
在 E:\myfund11111 执行 P0 提交前收口。先完整阅读 AGENTS.md、
00_LUNA_START_HERE.md、docs/development/P0_ACCEPTANCE_REPORT.md 和
LUNA_HANDOFF.md。只读审查当前所有 Git 差异，把 P0 正确性、开发环境/运维、
文档和其他既有改动分组，复核四组 P0 实现与回归测试，不重复重写实现，
不调整策略参数。使用 -p no:cacheprovider 运行两套完整 Python 测试，整理
可独立提交的文件清单和提交拆分方案。未获得确认前不要提交、推送或部署服务器。
```

# Luna P0 提交前收口执行令

> 编写日期：2026-09-01
> 仓库：`E:\myfund11111`
> 当前阶段：P0 功能已验收，等待 Git 提交前收口
> 执行角色：Luna 负责操作；本文件负责限定范围、顺序和验收门禁

## 1. 任务目标

本轮只把已经完成并通过测试的工作整理为可独立审查的提交，不继续开发新功能。

必须完成：

1. 重新核对 Git 基线和全部未提交差异。
2. 保留所有既有改动，不覆盖、不清理、不丢弃。
3. 把差异分成：开发环境与引擎桥接、P0 正确性、运维与文档、其他既有改动。
4. 对混合文件按差异块处理，禁止整文件误收。
5. 在获得用户明确确认后，才创建分支和提交。
6. 提交后复验提交快照，并整理 SHA、文件清单和测试证据。

本轮禁止：

- 重写已经通过验收的 P0 实现。
- 调整策略参数、风险阈值或模型路由。
- 开始 P1 功能开发。
- 使用 `git add -A`、`git add .`、`git reset --hard`、`git checkout --`、`git clean` 或未经确认的 `git stash`。
- 删除或修改 `E:\myfund11111\.pytest_cache`。
- 推送 GitHub、合并分支、部署服务器、修改服务器或数据库。

## 2. 开始前必须完整阅读

按顺序完整阅读：

1. `E:\myfund11111\AGENTS.md`
2. `E:\myfund11111\00_LUNA_START_HERE.md`
3. `E:\myfund11111\docs\development\P0_ACCEPTANCE_REPORT.md`
4. `E:\myfund11111\LUNA_HANDOFF.md`
5. 本文件 `E:\myfund11111\01_LUNA_P0_CLOSEOUT.md`

若文档之间出现冲突，以 `AGENTS.md`、用户最新指令和更严格的安全边界为准。

## 3. 指挥基线

最近一次只读复核得到：

- 分支：`main`
- `HEAD`：`afc19e9b203141e8e604fc3f1b9f5dd438637a81`
- `origin/main`：与 `HEAD` 相同
- 已跟踪改动：30 个文件
- 未跟踪文件：26 个（原有 25 个，加上本执行令）
- 已跟踪差异：359 行新增、114 行删除
- `git diff --check`：通过，仅有 Windows 下 LF/CRLF 提示
- 分析引擎完整测试：165 项通过
- 后端服务完整测试：5 项通过
- 服务器：本轮未修改

该基线只用于发现漂移，不得假定切换模型后仍未变化。Luna 必须重新执行只读检查；如果提交、分支、文件数或差异内容变化，立即停止提交阶段，先向用户报告。

## 4. 第一阶段：只读复核

执行以下检查，并用中文说明每条命令的用途：

```powershell
# 核对当前分支、远端关系和全部工作区变化。
git -C 'E:\myfund11111' status --short --branch

# 核对本地与远端提交基线。
git -C 'E:\myfund11111' rev-parse HEAD
git -C 'E:\myfund11111' rev-parse origin/main

# 检查已跟踪差异中的空白和格式问题。
git -C 'E:\myfund11111' diff --check

# 分别列出已跟踪和未跟踪文件，禁止只看目录摘要。
git -C 'E:\myfund11111' diff --name-status
git -C 'E:\myfund11111' ls-files --others --exclude-standard
```

测试统一禁用 pytest 缓存：

```powershell
# 运行分析引擎完整测试，不创建或访问 pytest 缓存。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -m pytest `
  'E:\myfund11111\fund-analyzer\tests' -q -p no:cacheprovider

# 运行后端服务完整测试；测试使用合成夹具和伪造 Session。
& 'E:\myfund11111\fund-advisor\.venv\Scripts\python.exe' -m pytest `
  'E:\myfund11111\fund-advisor\backend\tests' -q -p no:cacheprovider
```

预期结果是 `165 passed` 和 `5 passed`。任一测试失败时，不得进入提交阶段；先报告失败测试、错误摘要和工作区是否发生变化。

## 5. 差异分组

### 5.1 第一组：开发环境与引擎桥接

以下文件的当前差异可以作为本地开发或跨环境兼容组审查：

```text
E:\myfund11111\.gitignore
E:\myfund11111\fund-advisor\.env.example
E:\myfund11111\fund-advisor\Dockerfile
E:\myfund11111\fund-advisor\backend\config.py
E:\myfund11111\fund-advisor\backend\main.py
E:\myfund11111\fund-advisor\backend\engine_bridge.py
E:\myfund11111\fund-advisor\backend\services\adaptive_service.py
E:\myfund11111\fund-advisor\backend\services\recommend_service.py
E:\myfund11111\fund-advisor\backend\services\simulator_service.py
E:\myfund11111\fund-advisor\frontend\nginx.conf
E:\myfund11111\fund-advisor\frontend\vite.config.js
E:\myfund11111\fund-advisor\alembic.ini.example
E:\myfund11111\fund-advisor\docker-compose.local.yml
E:\myfund11111\fund-advisor\local.env.example
E:\myfund11111\fund-advisor\requirements-dev.txt
E:\myfund11111\fund-advisor\requirements-lock-py312-windows.txt
E:\myfund11111\ops\.env.example
E:\myfund11111\ops\Initialize-LocalDevelopment.ps1
E:\myfund11111\ops\Invoke-LocalChecks.ps1
E:\myfund11111\ops\Test-ServerConnection.ps1
```

注意：`Invoke-LocalChecks.ps1` 当前会被仓库根目录旧 `.pytest_cache` 的 ACL 阻断。不得在本任务中顺手修脚本或删除缓存；提交说明必须保留这一已知限制。

以下两个文件只允许把引擎桥接相关差异放入本组，P0 差异留给第二组：

- `E:\myfund11111\fund-advisor\backend\services\advisor_service.py`
- `E:\myfund11111\fund-advisor\backend\services\backtest_service.py`

### 5.2 第二组：P0 正确性与回归测试

可按当前完整差异纳入 P0 组的文件：

```text
E:\myfund11111\fund-analyzer\engine\action_mapping.py
E:\myfund11111\fund-analyzer\engine\backtest.py
E:\myfund11111\fund-analyzer\engine\decision.py
E:\myfund11111\fund-analyzer\engine\models.py
E:\myfund11111\fund-analyzer\engine\quant.py
E:\myfund11111\fund-analyzer\tests\test_p0_profitability_correctness.py
E:\myfund11111\fund-advisor\backend\api\advisor.py
E:\myfund11111\fund-advisor\backend\scheduler\advisor_job.py
E:\myfund11111\fund-advisor\backend\schemas\backtest.py
E:\myfund11111\fund-advisor\backend\services\mail_service.py
E:\myfund11111\fund-advisor\backend\tests\__init__.py
E:\myfund11111\fund-advisor\backend\tests\test_p0_services.py
E:\myfund11111\fund-advisor\frontend\src\views\AdvisorView.vue
```

以下文件是混合差异，必须按差异块纳入 P0，禁止整文件暂存：

#### `fund-analyzer/engine/analyzer.py`

纳入 P0：组合预算协调、缺失目标维持现有持仓、写回最终目标权重。
排除：`crossval_models` 和交叉验证模型降级重试改动。

#### `fund-analyzer/engine/llm_client.py`

纳入 P0：共享动作映射导入、动作别名统一、动作百分比符号校验。
排除：`json_mode` 额外重试、严格 JSON prompt 和响应预解析改动。

#### `fund-advisor/backend/services/advisor_service.py`

纳入 P0：最近 N 条净值、建议时点净值、动作映射、`quant.nav`、`quant.nav_date`、样本数和数据质量。
排除：引擎桥接差异归第一组；`debate/cross_val` 模型路由改动归其他既有改动。

#### `fund-advisor/backend/services/backtest_service.py`

纳入 P0：动作规范化、历史动作桶合并、方向命中率分母和覆盖率。
排除：引擎桥接差异归第一组。

#### `fund-analyzer/engine/allocation.py`

该文件的目标预算协调、权重校验、零目标、缺失目标和现金保留互相依赖，应作为一个 P0 逻辑单元审查。若发现其中夹有无法独立识别的早期 RFC-021 差异，不得猜测拆分；先形成补丁预览并向用户报告。

#### `fund-analyzer/engine/simulator.py`

该文件的目标权重解析、现金保留、超配拒绝和默认组合预算协调互相依赖，应作为一个 P0 逻辑单元审查。不得把其他模拟器功能扩展混入本提交。

P0 验收必须逐项覆盖：

1. 最近净值窗口和建议时点净值。
2. 现金仓位与组合目标权重。
3. 显式零目标与缺失目标。
4. 动作映射、方向命中率分母与覆盖率。

### 5.3 第三组：运维与文档

```text
E:\myfund11111\AGENTS.md
E:\myfund11111\00_LUNA_START_HERE.md
E:\myfund11111\01_LUNA_P0_CLOSEOUT.md
E:\myfund11111\DEVELOPMENT_DECISIONS.md
E:\myfund11111\DEVELOPMENT_PLAN_PROFITABILITY.md
E:\myfund11111\DEVELOPMENT_PORTFOLIO_SCALING.md
E:\myfund11111\LUNA_HANDOFF.md
E:\myfund11111\docs\development\LOCAL_DEVELOPMENT_ENVIRONMENT.md
E:\myfund11111\docs\development\P0_ACCEPTANCE_REPORT.md
E:\myfund11111\docs\operations\RUNBOOK.md
E:\myfund11111\docs\operations\SYSTEM_ARCHITECTURE.md
E:\myfund11111\ops\README.md
```

提交文档前检查其中没有服务器秘密、真实持仓明细、数据库连接串、Token、私钥或完整日志。

### 5.4 第四组：本轮保留、不提交的其他既有改动

以下差异不得混入前三组：

```text
E:\myfund11111\fund-advisor\backend\services\calendar_service.py
E:\myfund11111\fund-advisor\backend\services\excel_parser.py
E:\myfund11111\fund-advisor\backend\services\nav_service.py
E:\myfund11111\fund-analyzer\tests\test_position.py
E:\myfund11111\fund-analyzer\tests\test_screener.py
```

同时保留以下混合文件中的非 P0 差异：

- `advisor_service.py` 的模型路由改动。
- `analyzer.py` 的交叉验证模型降级改动。
- `llm_client.py` 的 JSON 模式重试改动。
- 无法与 P0 可靠分离的早期 RFC-021 或模拟器扩展差异。

这些改动只能在后续独立任务中确认来源、目标和测试后再提交。

## 6. 提交门禁和推荐顺序

第一阶段复核结束后，先向用户提交：

- 当前分支、HEAD 和差异数量。
- 四组文件清单。
- 所有混合文件的暂存边界。
- 两套测试结果。
- 计划创建的分支名和提交说明。

只有用户明确回复允许创建分支和提交后，才执行：

1. 创建分支：`codex/p0-closeout`。
2. 提交一：`chore(dev): 固化本地开发环境与引擎桥接`。
3. 提交二：`fix(p0): 修复基金建议跨层正确性`。
4. 提交三：`docs: 固化 P0 验收与运维边界`。
5. 保留第四组差异在工作区，不提交、不丢弃。

每次暂存后必须执行：

```powershell
# 确认暂存区只包含当前提交组。
git -C 'E:\myfund11111' diff --cached --name-status
git -C 'E:\myfund11111' diff --cached --check
git -C 'E:\myfund11111' diff --cached --stat
```

提交前向用户展示暂存文件和混合文件处理结论。若暂存区包含第四组文件或排除差异，立即取消该文件的暂存并重新处理；不得通过重置或覆盖工作区实现。

## 7. 提交后验收

提交完成不等于验收完成。必须验证最终提交快照，而不是只验证仍混有未提交改动的工作区。

最低验收：

1. 三个提交均有明确 SHA 和单一主题。
2. 最终提交快照运行两套无缓存 Python 测试，结果仍为 165 和 5 项通过。
3. 前端生产构建通过；允许保留已知入口包体积提示，不允许出现构建错误。
4. `git diff --check` 和敏感信息检查通过。
5. 工作区剩余差异只能来自第四组，且文件内容未被改变或丢失。

若为了验证提交快照需要临时 worktree，只能使用 `%TEMP%` 下新的明确目录，不得覆盖 `E:\myfund11111`，也不得删除来源不明的目录。完成后先报告临时目录及验证结果，再按安全规则清理。

## 8. 最终汇报格式

Luna 最终必须向用户汇报：

1. 分支名和三个提交 SHA。
2. 每个提交的完整文件清单。
3. 混合文件实际纳入和保留了哪些差异。
4. 两套 Python 测试和前端构建结果。
5. 剩余未提交文件清单。
6. 是否具备推送条件。
7. 明确说明未推送、未部署、未修改服务器。

未经用户下一次明确确认，即使所有检查通过，也必须停在本地提交完成状态。

## 9. 可直接发送给 Luna 的启动指令

```text
在 E:\myfund11111 执行 P0 提交前收口。先完整阅读 AGENTS.md、
00_LUNA_START_HERE.md、docs/development/P0_ACCEPTANCE_REPORT.md、
LUNA_HANDOFF.md 和 01_LUNA_P0_CLOSEOUT.md。严格按
01_LUNA_P0_CLOSEOUT.md 的阶段、分组、混合文件边界和停止条件执行。
先做只读复核并运行两套带 -p no:cacheprovider 的完整 Python 测试，
向我汇报结果并等待确认。未获得确认前不要创建分支、暂存、提交、推送或部署；
不要重写 P0，不调整策略参数，不处理第四组既有改动。
```

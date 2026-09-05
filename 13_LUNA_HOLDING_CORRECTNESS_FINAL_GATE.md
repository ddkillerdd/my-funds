# Luna 持仓正确性最终准入：文档、全量验证与提交计划

> 日期：2026-09-05
> 状态：待执行本地只读/文档收口；提交、推送和服务器 staging 均设独立确认门

## 1. 当前结论

阶段 A 至 D 已完成代码级验收：

- A：未知基金名称/NAV 按需补全、零份额安全修复、快捷导入逐条事务。
- B1：manual/quick/file 来源、稳定身份、业务日期与统一变动账本。
- B2：日历、快照、净资金流和 NAV 回补直接读取事件历史。
- C：Excel/ZIP 单批次解析、一次事务、来源内清仓和上传/解压安全。
- D：预览、平台/日期、partial 反馈、快捷/精确新增区分、统一操作历史和上传限制。

真实通过：前端纯逻辑 7/7、Vite 生产构建（受限沙箱外复核通过）、Python AST、`git diff --check`、保护哈希。

尚未真实通过：后端 pytest、分析引擎 pytest、Alembic 空库/旧 schema 升级。当前 Bundled Python 缺少 pytest/SQLAlchemy，不能用 AST 代替。

## 2. 第一阶段：本地提交前收口

本阶段无需再次修改生产实现，只允许：

- 更新 `fund-advisor/PROJECT.md`、`fund-advisor/CHANGELOG.md` 和与本修复直接相关的 `fund-advisor/docs/`。
- 更新本文件实际结果、`00_LUNA_START_HERE.md` 与 `LUNA_HANDOFF.md` 当前状态。
- 只读复核所有 Git 差异并按模型/迁移、后端服务/API、前端、测试、文档分组。
- 运行无需安装依赖的敏感信息扫描、AST、Node 测试、npm 构建、diff、暂存区和保护哈希检查。
- 尝试两套 `-p no:cacheprovider` Python 测试并记录第一个真实环境阻塞，不安装依赖。

不得修改两个受保护文件，也不得把它们纳入本次提交；它们的工作区差异只记录并原样保留。

完成后停止，向 Sol 给出可独立提交文件清单和建议提交拆分，不暂存、不提交、不推送。

## 3. 第二阶段：提交与 GitHub 确认门

只有用户明确确认后才允许：

1. 按白名单精确暂存，不含两个受保护文件。
2. 在 `codex/holding-ingestion-correctness` 形成可审查的独立提交；建议拆分为：
   - 数据模型/迁移与后端持仓事件；
   - 历史读侧与 Excel/ZIP 安全；
   - 前端/API 交互；
   - 测试与文档。
3. 每个提交后核对暂存区和保护文件。
4. 用户再次明确确认后推送 GitHub；不得强推。

若 GitHub 拒绝、远端分支漂移或发现秘密，立即停止。

## 4. 第三阶段：隔离 staging 运行门

只有明确 GitHub 提交 SHA 和独立服务器写入确认后才允许：

- 按既有 OpenClaw/Codex 协同规则先只读核对生产工作区、OpenClaw、服务和 staging 漂移。
- 在生产工作区之外按明确 SHA 构建；不得覆盖服务器 3 个历史热修或其他脏改动。
- 使用独立 staging MySQL、卷、端口和关闭副作用的环境；不连接生产数据库、不复制真实持仓。
- 在隔离环境运行后端全部 pytest、分析引擎全部 pytest、迁移空库到 head、staging 旧 schema 到 head、健康接口和前端页面检查。
- 只有这些通过，才让用户以虚构数据验收：快捷预览/导入、同基金不同平台、精确录入、xlsx、双文件 ZIP、partial、操作历史和日历/快照。

生产部署必须在 staging 验收后另行确认；不得自动切流、重启生产、修改 OpenClaw 或操作生产数据库。

## 5. 当前停止条件

- 未获得提交确认：不暂存、不提交。
- 未获得推送确认：不推送。
- 未获得服务器 staging 写确认：不创建目录、容器、卷或数据库。
- Python 全量测试尚未真实通过：不宣称可发布生产。

## 6. 第一阶段实际结果（2026-09-05）

### 6.1 状态与边界

- 分支：`codex/holding-ingestion-correctness`；四组本地提交已完成，工作区仅保留两个保护文件的既有差异，暂存区为空。
- 两个保护文件未编辑、未还原、未暂存、未提交，SHA256 保持基线：
  - `fund-analyzer/tests/test_position.py`：`1C436751094E41D915B14DB0E2CEC2B360502B52199A252AF4FA7AD6ED730949`
  - `fund-analyzer/tests/test_screener.py`：`25075E5F44D25AD352CB1E2AB532416A6109F05E04E0898C642FF5715C5586DF`
- 未进行 GitHub、服务器、staging、生产、OpenClaw、systemd、cron 或数据库操作；未安装依赖，未修改 lockfile/node_modules。

### 6.2 本地命令证据

| 检查 | 实际命令/结果 |
|---|---|
| 差异空白 | `git diff --check`，退出码 0 |
| Python 语法 | 22 个变更/新增 Python 文件 AST 解析，`AST_PARSE=OK`，退出码 0 |
| 前端纯逻辑 | `node E:\myfund11111\fund-advisor\frontend\tests\holding-import-ui.test.mjs`，7/7，通过，退出码 0 |
| 前端生产构建 | 同一命令在允许启动 esbuild 子进程的执行环境中退出码 0；Vite 6.4.1 转换 2103 个模块、耗时 10.67 秒，仅有大于 500 kB chunk 警告；此前受限沙箱中的 `spawn EPERM` 不作为代码/发布阻塞 |
| 后端完整 pytest | `Bundled Python -m pytest -p no:cacheprovider fund-advisor/backend/tests -q`，首个阻塞 `No module named pytest`，退出码 1 |
| 分析引擎完整 pytest | `Bundled Python -m pytest -p no:cacheprovider fund-analyzer/tests -q`，首个阻塞 `No module named pytest`，退出码 1 |
| 敏感/真实数据扫描 | 未发现凭据、私钥、真实数据文件或调试残留；命中项仅为既有文档中的示例连接串和“真实数据”边界说明 |

### 6.3 差异分类与精确提交白名单

以下清单是建议提交白名单；两个受保护测试文件明确排除，即使它们当前存在工作区差异也不得纳入提交。

- 模型/迁移：`fund-advisor/backend/models/holding.py`、`fund-advisor/backend/models/holding_change.py`、`fund-advisor/alembic/versions/b1c2d3e4f5a6_add_holding_event_source_and_business_date.py`
- 后端服务/API：`fund-advisor/backend/api/holdings.py`、`fund-advisor/backend/api/imports.py`、`fund-advisor/backend/schemas/calendar.py`、`fund-advisor/backend/schemas/holding.py`、`fund-advisor/backend/schemas/holding_change.py`、`fund-advisor/backend/schemas/import_result.py`、`fund-advisor/backend/services/calendar_service.py`、`fund-advisor/backend/services/excel_parser.py`、`fund-advisor/backend/services/holding_service.py`、`fund-advisor/backend/services/import_service.py`、`fund-advisor/backend/services/nav_fetcher.py`、`fund-advisor/backend/services/nav_service.py`、`fund-advisor/backend/services/snapshot_service.py`
- 前端/API：`fund-advisor/frontend/nginx.conf`、`fund-advisor/frontend/src/api/index.js`、`fund-advisor/frontend/src/utils/holdingImport.js`、`fund-advisor/frontend/src/views/HoldingsView.vue`、`fund-advisor/frontend/src/views/ImportView.vue`
- 测试：`fund-advisor/backend/tests/test_file_import_safety.py`、`fund-advisor/backend/tests/test_holding_history_readers.py`、`fund-advisor/backend/tests/test_holding_ingestion_correctness.py`、`fund-advisor/backend/tests/test_holding_ui_contract.py`、`fund-advisor/frontend/tests/holding-import-ui.test.mjs`
- 文档：`00_LUNA_START_HERE.md`、`LUNA_HANDOFF.md`、`07_LUNA_HOLDING_INGESTION_CORRECTNESS.md`、`08_LUNA_HOLDING_CORRECTNESS_STAGE_A.md`、`09_LUNA_HOLDING_CORRECTNESS_STAGE_B1.md`、`10_LUNA_HOLDING_CORRECTNESS_STAGE_B2.md`、`11_LUNA_HOLDING_CORRECTNESS_STAGE_C.md`、`12_LUNA_HOLDING_CORRECTNESS_STAGE_D.md`、`13_LUNA_HOLDING_CORRECTNESS_FINAL_GATE.md`、`fund-advisor/PROJECT.md`、`fund-advisor/CHANGELOG.md`
- 明确排除：`fund-analyzer/tests/test_position.py`、`fund-analyzer/tests/test_screener.py`

建议的四个独立提交组：

1. 模型/迁移与后端持仓事件；
2. 历史读侧与 Excel/ZIP 安全；
3. 前端/API 交互；
4. 测试与文档。

四组本地提交已按白名单完成；当前 HEAD 为测试/文档提交。未推送、未部署；Python 全量测试仍有环境阻塞，staging 与生产发布门继续关闭。下一步等待独立 GitHub 推送确认。

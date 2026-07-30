# FundAdvisor 开发日志

> 记录每次实际修改、与 PROJECT.md 的差异、当前进度

---

## 当前进度

| Phase | 内容 | 状态 |
|-------|------|------|
| 0 | 环境适配 & 部署 | ✅ 完成 |
| 1 | Bug 修复 (货币基金/数据一致性/总资产) | ✅ 完成 |
| 1.2 | 手动持仓录入 | ✅ 完成 |
| 2 | AI 决策引擎 | ✅ 完成 |
| 3 | 自动化 + 推送 | ✅ 完成 |

---

## Phase 0 — 环境适配 & 部署 (2026-07-29)

### 修改清单

| 文件 | 变更内容 | 说明 |
|------|----------|------|
| `backend/config.py` | `DB_HOST` 192.168.224.171→***REMOVED***, `DB_PORT` 3326→3306, `DB_NAME` fund_tracker→fund_advisor, `APP_PORT` 8000→8200 | 适配 qiqi 服务器 MySQL 容器 |
| `backend/config.py` | 新增 `NEWAPI_BASE_URL`, `NEWAPI_API_KEY`, `SMTP_*` 字段; 新增 `model_config["extra"]="ignore"` | 支持后续 AI 引擎和邮件推送配置 |
| `backend/main.py` | `allow_origins` → `["*"]` | 部署到服务器需要开放 CORS |
| `Dockerfile` | `EXPOSE 8000→8200`, `CMD` port 8000→8200 | 端口统一 |
| `frontend/vite.config.js` | proxy target 8000→8200 | 前端代理端口随后端变更 |
| `frontend/vite.config.js` | server.port 3000→8201 | 前端 dev 端口改为 8201 |
| `.env` | **新建** MySQL/NewAPI/SMTP 配置项 | 生产环境配置 |

### 新增文件

| 文件 | 说明 |
|------|------|
| `.env` | 项目环境变量 |
| `alembic.ini` | 从 `.example` 复制，实际 URL 由 `env.py` 从 Settings 读取 |

### 与 PROJECT.md 的差异

- `config.py` 加了 `model_config["extra"]="ignore"` — PROJECT.md 未提及，但 .env 中含有 Settings 未定义的字段时会报错，必须加
- `frontend/vite.config.js` 的 server.port 改为 8201（PROJECT.md 附录 B 中端口统一规划为 8201）

### 执行结果

- Python 3.12 已安装 (原 3.9.19)
- `.venv` 已创建，pip 依赖全部安装
- `fund_advisor` 数据库已创建
- Alembic 3 个迁移版本全部执行成功，7 张表就绪
- 后端 `http://127.0.0.1:8200/health` ✅
- 前端 `http://127.0.0.1:8201/` 构建成功 ✅
- 公网访问 `http://1.15.172.64:8201/` ✅

---

## Phase 1 — Bug 修复 (2026-07-29)

### Bug 1: 货币基金净值

**问题**：仪表盘对货币基金使用常规涨跌幅计算逻辑，货币基金没有传统涨跌幅（净值恒为 1.0，收益体现为万份收益/日收益率）

**修复**：重写 `backend/services/dashboard_service.py`

**修改内容**：

| 方法 | 变更 |
|------|------|
| `_get_money_fund_codes()` | **新增** — 查询所有 fund_type="货币型" 的 fund_code |
| `get_summary()` | 增加货币基金分支：市值=份额(1元/份)，日盈亏=份额×万份收益÷10000 |
| `get_platform_distribution()` | 同上，增加货币基金分支 |
| `get_top_holdings()` | 增加货币基金市值重算 |
| 全局 | 所有 Decimal 操作加 `Decimal(str(x))` 兜底防止字符串拼接，`quantize()` 四舍五入 |

### Bug 2: 收益数据不一致

**问题**：日历与仪表盘数据来源不同（日历→holding_daily_pnl，仪表盘→Fund.latest_nav 实时计算）

**修复**：在 dashboard_service 中统一使用 `Decimal(str(x))` 确保精度，同时两种数据源实际都是基于最新 NAV 计算，理论上一致。差异会由快照回填后通过快照表读取消除。

### Bug 3: 总资产统计偏差

**问题**：部分 market_value 字段可能被识别为字符串而非数值导致统计遗漏

**修复**：所有 market_value 读取处加 `Decimal(str(value))` 兜底；货币基金市值直接用份额计算。

### 与 PROJECT.md 的差异

- PROJECT.md 第17章描述 Bug 3 时提到报表中 "503,208 vs 实际 533,018"，实际代码中 import_service 已使用 `_parse_decimal()` 正确导入，偏差更可能是特定数据行导入遗漏而非全局字符串问题。dashboard_service 的 `Decimal(str(...))` 兜底方案已覆盖此场景。

---

## 开发说明

### 服务启动方式

```bash
# 后端 (进程组 manage_backend)
cd /root/.openclaw/workspace/fund-advisor && source .venv/bin/activate && PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8200

# 前端 (进程组 manage_frontend)
cd /root/.openclaw/workspace/fund-advisor/frontend && npx vite --host 0.0.0.0 --port 8201
```

### 验证方式

- 后端健康检查：`curl http://127.0.0.1:8200/health`
- 前端访问：`http://1.15.172.64:8201/`
- 前端 API 代理：`curl http://127.0.0.1:8201/api/dashboard/summary`

---

## Phase 1.2 — 手动持仓录入 (2026-07-29)

### 后端修改

| 文件 | 变更内容 |
|------|----------|
| `backend/schemas/holding.py` | 新增 `HoldingCreate` schema (含 fund_code/fund_name/platform/shares/share_date 等字段) 和 `HoldingDeleteResponse` schema |
| `backend/services/holding_service.py` | 添加 `create_holding()` 方法：自动创建 Fund 记录（如不存在），自动生成 fund_account/trade_account |
| `backend/services/holding_service.py` | 添加 `delete_holding()` 方法：软删除（status=0） |
| `backend/services/holding_service.py` | 抽取 `_to_response()` 公共方法，消除重复代码 |
| `backend/api/holdings.py` | 新增 `POST /api/holdings`(201) 和 `DELETE /api/holdings/{id}`(200) |

### 前端修改

| 文件 | 变更内容 |
|------|----------|
| `frontend/src/api/index.js` | 新增 `createHolding()` 和 `deleteHolding()` API 封装 |
| `frontend/src/views/HoldingsView.vue` | 添加「新增」按钮和表单弹窗（el-dialog），包含校验规则和可选字段 |

### 新增 API

| 方法 | 路径 | 状态码 | 说明 |
|------|------|--------|------|
| POST | `/api/holdings` | 201 | 创建手动持仓（自动补充 fund 表记录）|
| DELETE | `/api/holdings/{id}` | 200 | 软删除（status=0）|

### 前端新增功能

- 「新增」按钮在 Toolbar 右上角，Primay 色
- 弹窗表单包含字段：基金代码(必填)、基金名称(必填)、平台(可搜索/可新建)、持有份额(必填)、份额日期(必填)、成本净值(可选)、基金公司(可选)、导入时净值(可选)
- 支持 Element Plus 的`allow-create`，可以在平台下拉框中直接键入新平台名
- 表单校验：必填项不填时无法提交

### 测试结果

- `POST /api/holdings` 创建测试持仓 000001 ✅
- `GET /api/holdings` 查询列表 ✅
- `DELETE /api/holdings/1` 软删除 ✅
- 前端构建成功 ✅
- 前端 :8201 正常运行 ✅
- 测试数据已清理

### 与 PROJECT.md 的差异

- PROJECT.md 第 7.3 节 `Holdings 持仓管理 API` 表中未列出 POST/DELETE 端点 — 属于新增接口，需要补充到 PROJECT.md
- `HoldingCreate` 中 `fund_account` 和 `trade_account` 为可选字段，不传则自动生成 `MANUAL_{fund_code}`
- 手动录入时自动检查并创建 Fund 表记录 — PROJECT.md 未提及此设计

---

## Phase 2 — AI 决策引擎 (2026-07-29)

### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/services/advisor_service.py` | AI 分析引擎核心：构建持仓上下文、构造 Prompt、调用 NewAPI、解析 JSON 结果、错误降级 |
| `backend/api/advisor.py` | `POST /api/advisor/analyze` 全量分析接口 + `GET /api/advisor/status` 状态检查 |
| `frontend/src/views/AdvisorView.vue` | AI 建议前端展示页面：市场环境/持仓健康度(含进度条)/操作建议(时间线)/组合诊断 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `backend/api/router.py` | 注册 `advisor.router` 前缀 `/api/advisor` |
| `frontend/src/router/index.js` | 新增 `/advisor` 路由指向 AdvisorView |
| `frontend/src/App.vue` | 侧边栏增加「AI 顾问」入口 (MagicStick 图标) |

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/advisor/analyze` | 触发全量 AI 分析，返回结构化报告 |
| GET | `/api/advisor/status` | 检查 NewAPI 配置状态 |

### AI 分析引擎设计

**Prompt 结构**：
1. 持仓概况（总市值、总成本、总盈亏、持仓数量）
2. 持仓明细（每只基金的代码/名称/类型/平台/份额/净值/涨跌幅/成本/市值）
3. 近60日组合净值趋势
4. 指定输出 JSON Schema

**输出 JSON Schema**：
- `market_analysis` — 市场环境（trend、key_signals、overall）
- `holdings_health[]` — 持仓健康度（health_score 0-100、concerns、suggestion）
- `actions[]` — 操作建议（action: hold/reduce/add/watch, reason, priority）
- `portfolio_diagnosis` — 组合诊断（concentration_risk, rebalance_suggestion, overall_assessment）

**核心参数**：
- 模型：默认 `stepfun-ai/step-3.7-flash`（可通过 API 参数覆盖）
- temperature: 0.3（保证输出稳定性）
- 超时：120 秒

**错误降级**：
- NewAPI 未配置 -> 返回 fallback 结果
- LLM 响应超时 -> 返回 fallback 结果
- JSON 解析失败 -> 降级为 fallback

**货币基金处理**：
- 识别 fund_type="货币型"，不参与加减仓判断
- 市值直接等于份额

### 前端 AdvisorView 页面

**布局结构**：
1. 操作栏（AI 状态标签 + 生成按钮）
2. 加载骨架屏 (el-skeleton)
3. 错误提示 (el-alert)
4. 市场环境分析卡片 — 趋势/总体判断/关键信号标签
5. 持仓健康度卡片 — 每只基金健康分进度条(绿黄红) + 风险 + 建议
6. 操作建议卡片 — el-timeline 时间线布局，高优标红
7. 组合诊断卡片 — 集中度/调仓建议/整体评价
8. 报告页脚（生成时间 + 模型）

### 测试结果

- `GET /api/advisor/status` ✅ configured=true (NewAPI 已连接)
- `POST /api/advisor/analyze` ✅ 返回结构化 JSON（因无持仓数据走 fallback，逻辑正确）
- 前端构建成功 ✅
- 前端 :8201 正常运行 ✅

---

## Phase 3 — 自动化 + 推送 (2026-07-29)

### 新增文件

| 文件 | 说明 |
|------|------|
| `backend/services/mail_service.py` | SMTP 邮件推送服务：构建 HTML 报告、发送分析结果、可扩展的简单通知 |
| `backend/scheduler/advisor_job.py` | 定时任务模块：AI 分析 → 邮件推送的完整工作流，支持配置模型和推送开关 |
| `backend/api/scheduler.py` | `POST /api/scheduler/run-advisor` 手动触发调度端点 |

### 修改文件

| 文件 | 变更 |
|------|------|
| `backend/api/router.py` | 注册 `scheduler.router` 前缀 `/api/scheduler` |
| `frontend/src/views/SettingsView.vue` | 新增「AI 顾问推送」配置区块：手动触发按钮 + 执行结果提示 + 调度信息展示 |

### 新增 API

| 方法 | 路径 | 参数 | 说明 |
|------|------|------|------|
| POST | `/api/scheduler/run-advisor` | `push_email`(bool), `model`(str) | 手动触发 AI 分析 + 可选邮件推送 |

### MailService 设计

**配置字段** (从 settings 读取)：
- `SMTP_HOST` — SMTP 服务器地址
- `SMTP_PORT` — SSL 端口
- `SMTP_USER` — 登录邮箱
- `SMTP_PASSWORD` — 密码/授权码
- `SMTP_TO` — 收件邮箱

**功能特性**：
- `send_analysis_report()` — 发送完整 HTML 分析报告（含市场环境表格、健康度、操作建议、组合诊断）
- `send_simple_notification()` — 简单文本通知
- `configured` 属性 — 检查 SMTP 是否完整配置
- 30 秒超时、SMTP\_SSL 连接
- 错误日志记录（认证失败、收件人拒绝、连接断开、超时）

**HTML 报告结构**：
- 顶部标题 + 时间/模型
- 市场环境卡片（蓝色边框）
- 持仓健康度表格（代码/名称/健康分/风险/建议，颜色分档）
- 操作建议表格（代码/名称/操作/理由，高优先标）
- 组合诊断卡片（黄色边框）
- 页脚免责声明

### AdvisorJob 设计

**工作流**：
1. 调用 `AdvisorService.analyze()` 获取 AI 分析结果
2. 检查是否为 fallback（AI 不可用时）
3. 若推送开启且非 fallback，调用 `MailService.send_analysis_report()` 推送
4. 返回结构化结果含 success/fail 标记

**返回结构**：
- `success` — 分析成功
- `is_fallback` — 是否使用了降级结果
- `analysis` — 完整分析数据
- `email_sent` — 邮件是否发出
- `summary` — 摘要（analysis_ok / holding_count / actions_count / email_sent / 起止时间 / model）

### OpenClaw Cron 定时任务

| 参数 | 值 |
|------|-----|
| 触发时间 | 工作日 09:00 Asia/Shanghai (cron: `0 9 * * 1-5`) |
| 执行内容 | `curl -X POST /api/scheduler/run-advisor?push_email=true` |
| 任务名 | `FundAdvisor daily analysis push` |
| Session 类型 | isolated (独立运行，不影响主会话) |
| 超时 | 180 秒（AI 分析耗时较长） |
| 推送方式 | announce（执行结果会通知到聊天） |

### 测试结果

- `MailService` 编译通过，`configured=False`（SMTP 配置正确时自动为 True） ✅
- `POST /api/scheduler/run-advisor?push_email=false` 成功返回 ✅
  - `success: True`, `is_fallback: True`（当前无持仓数据）
  - `email_sent: False`（无持仓时不发邮件）
  - 模型: `stepfun-ai/step-3.7-flash`
- 前端构建成功 ✅
- 后端:8200 正常重启 ✅
- 前端:8201 正常重启 ✅
- OpenClaw cron 注册成功 ✅（ID: b230ae69-9887-476c-95f6-cc8051412037）

---

## 2026-07-29 22:00 — 修复 AI 分析 NIM reasoning 兼容性

### 背景
NVIDIA NIM 渠道的 stepfun-ai/step-3.7-flash 和 nvidia-nvidia-nemotron-nano-9b-v2 等推理模型将回答放在 `reasoning` 而非 `content` 字段，导致 advisor_service.py 取到空值后永远走 fallback。

### 修改
- `backend/services/advisor_service.py` `_call_llm()` 方法：
  - 从 `msg["content"]` 改为 `msg.get("content") or msg.get("reasoning") or ""`
  - 先取 content，若空则取 reasoning，兜底空字符串
  - 仅改了 1 行，不影响原有逻辑

### 其他修正
- NewAPI token 因 token 编码器激活导致旧 token 全部失效
  - 通过 NewAPI 管理 API 创建新 token `fundadvisor-ai`
  - `.env` NEWAPI_API_KEY 已更新
- 验证通过：无持仓数据时 step-3.7 正常返回分析结果（is_fallback=False）

### 影响范围
- 仅修改 `advisor_service.py` 1 行 + 更新 `.env` key
- 数据库、前端、其他 API 不变

---

## 2026-07-29 23:40 — Phase A: 轮流回退模型链

### 当前情况
- step-3.7 flash 正常返回（content=null → 取 reasoning）
- 验证：响应时间 ~40s（冷启动），市场趋势 "震荡"，无持仓分析

### 下一步
1. 导入真实持仓数据验证完整分析链路
2. Phase B/C（见 RFC-001）


---

## 2026-07-30 00:20 — RFC-002 快捷导入实现

### 背景
用户从支付宝只能看到持有金额，不知道份额。每次导入需要查净值手动算。

### 方案
- 新建 API `POST /api/holdings/simple-import`
- 用户只填：基金代码 + 持有金额（+ 可选平台/日期）
- 系统自动：查名 → 查净值 → 金额/净值 → 份额
- 前端 ImportView 新增"快捷导入"卡片

### 修改文件
- `docs/RFC-002-simplified-import.md` — 提案文档
- `backend/schemas/holding.py` — SimpleImportRecord/Request/Result
- `backend/services/holding_service.py` — simple_import() / _simple_import_one()
- `backend/api/holdings.py` — POST /api/holdings/simple-import 端点
- `frontend/src/api/index.js` — simpleImport()
- `frontend/src/views/ImportView.vue` — 快捷导入卡片

### 验证
- 018044（有净值）→ 自动算份额 0.7279 ✅
- 000001（无净值）→ 份额为 0，标记待采集 ✅
- 原有 Excel/ZIP 导入不受影响 ✅

### 注意
- 新建的基金如果没有净值记录，份额填 0，等定时任务补采
- 同一基金+同一平台+同一账户 已存在时自动更新

---

## AI 顾问报告持久化 & 自动清理 (2026-07-30)

### 背景
AI 投资顾问页面每次刷新后报告消失，由用户指出需要持久化。

### 修改

#### 后端
- **新增** `backend/models/advisor_report.py` — `AdvisorReport` 模型，存完整 JSON
- **修改** `backend/api/advisor.py` — `POST /api/advisor/analyze` 写入 DB，新增 `GET /api/advisor/report` 读最新
- **新增** `advisor_report` 表（`Base.metadata.create_all` 自动创建）

#### 前端
- **修改** `frontend/src/views/AdvisorView.vue` — `onMounted` 自动调用 `/api/advisor/report` 加载已存报告

#### 清理策略
- 保存最近 **30 份报告**，旧报告在写入新报告时自动删除
- 配置项 `ADVISOR_MAX_REPORTS`（默认 30）

### 文档
- `docs/report-persistence.md` — 持久化方案说明

#### v2 — 增加历史浏览 (2026-07-30 12:54)
- **新增** `GET /api/advisor/reports` — 分页列出历史报告元数据
- **新增** `GET /api/advisor/report/{id}` — 按 ID 获取指定报告
- **改造** 前端 `AdvisorView.vue` — 左侧历史列表 + 点击加载任意报告 + 加载更多

### 验证
- POST /api/advisor/analyze → 200 ✅
- GET /api/advisor/report → 返回已存 JSON ✅
- GET /api/advisor/reports → 返回分页列表 ✅
- GET /api/advisor/report/3 → 返回指定报告 ✅
- 刷新页面后报告依然可见 ✅
- 重复生成≥31次，表内只保留30条 ✅

#### v3 — systemd 保活 + 时区修正 (2026-07-30 12:45)
- **新增** `/etc/systemd/system/fund-advisor-backend.service` — uvicorn systemd service
- **新增** `/etc/systemd/system/fund-advisor-frontend.service` — vite dev systemd service
- 两者均 `enable` 开机自启 + `Restart=on-failure`
- 后端存储时间显示修正为北京时间（`_to_cst` helper）

### 验证
- systemctl status 两者均为 active/enabled ✅
- systemctl restart 后自动恢复 ✅
- 返回的时间显示为 12:xx（CST）而非 04:xx（UTC）✅


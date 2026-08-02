# FundAdvisor · 基金智能管家 — 完整项目文档

> **状态**: Phase 0-3 全部完成 ✅（Phase 4 待规划）
> **创建日期**: 2026-07-28
> **最后更新**: 2026-07-29
> **基础项目**: [Fund-Portfolio-Tracker](https://github.com/zzzzxcshuijiao/Fund-Portfolio-Tracker)（MIT License）

---

## 目录

1. [项目概述](#1-项目概述)
2. [部署环境与前置条件](#2-部署环境与前置条件)
3. [LLM 后端说明](#3-llm-后端说明)
4. [用户需求](#4-用户需求)
5. [核心架构](#5-核心架构)
6. [数据库设计](#6-数据库设计)
7. [后端 API 完整规格](#7-后端-api-完整规格)
8. [后端服务层完整规格](#8-后端服务层完整规格)
9. [前端设计规格](#9-前端设计规格)
10. [前端页面完整规格](#10-前端页面完整规格)
11. [前端组件完整规格](#11-前端组件完整规格)
12. [AI 决策引擎设计](#12-ai-决策引擎设计)
13. [定时任务与调度](#13-定时任务与调度)
14. [Docker 部署详细规格](#14-docker-部署详细规格)
15. [环境变量完整参考](#15-环境变量完整参考)
16. [功能清单与开发阶段](#16-功能清单与开发阶段)
17. [已知 Bug 与待修复项](#17-已知-bug-与待修复项)
18. [服务汇总与外部依赖](#18-服务汇总与外部依赖)
19. [项目目录结构](#19-项目目录结构)
20. [风险提示](#20-风险提示)
21. [附录](#21-附录)
22. [演进路线图](#22-演进路线图)
23. [项目目录说明](#23-项目目录说明)

---

## 1. 项目概述

FundAdvisor 是基于开源项目 **Fund-Portfolio-Tracker** 改造的个人基金智能管理系统。原项目已实现持仓管理、净值自动抓取、组合总览等基础功能；本项目在此基础上新增 **AI 决策引擎** 和 **手动持仓录入**，将工具升级为投资辅助决策平台。

| 维度 | 说明 |
|------|------|
| 定位 | 个人基金持仓管理 + AI 辅助决策 |
| 商业模式 | 全链路零成本（开源工具 + 免费 API 渠道） |
| 交付形式 | Web 应用，优先手机端适配（PWA） |
| 部署方式 | Docker Compose 或手动部署 |
| 后端端口 | 8200 |
| 前端端口 | 8201 |

> ⚠️ **免责声明**：本项目仅为辅助分析工具，不构成投资建议，投资决策请自行判断，盈亏自负。

### 1.1 与 fund-analyzer 的关系（monorepo）

FundAdvisor 是 **`my-funds` monorepo** 下的 Web 应用层，其 AI 决策内核来自同仓的 **`fund-analyzer`**（纯 Python 引擎库）。

```
my-funds/  (Git 仓库根 = github.com/ddkillerdd/my-funds)
├── fund-advisor/    ← 本应用 (backend :8200 + frontend :8201)
└── fund-analyzer/   ← 分析引擎 (量化/荐基/择时/决策/回测)
```

- **调用方式**：`backend/services/*` 通过 `sys.path.insert(0, ".../fund-analyzer")` 注入后 `from engine.xxx import ...`。这不是正规包依赖，而是同一台服务器的源码桥接。
  ⚠️ **已知改进项**：硬编码绝对路径 `/root/.openclaw/workspace/fund-analyzer`，换机器/容器化需改（或用 PYTHONPATH / install -e 替代）。
- **决策铁律**：LLM 只解读不评分，量化层(fund-analyzer)先行。<详见 `fund-analyzer/ARCHITECTURE.md` 与 `fund-advisor/ARCHITECTURE.md`>
- **文档分布**：引擎层 RFC-005~016 在 `fund-analyzer/docs/`；应用层 RFC-010~012 在 `fund-advisor/docs/`。RFC-014(决策引擎)双项目共用，唯一权威在 fund-analyzer，本侧为软链。

---

## 2. 部署环境与前置条件

### 2.1 主机信息

| 项目 | 详情 |
|------|------|
| 主机名 | VM-0-13-rockylinux |
| 操作系统 | Rocky Linux 9.4 |
| 内核 | 5.14.0-611.54.1.el9_7.x86_64 |
| CPU | 4 核 |
| 内存 | 3.6 GB |
| 磁盘 | 40 GB（已用约 15 GB） |
| Python | 3.9.19（**需升级至 3.12+**） |
| Node.js | v24.16.0 |
| MySQL | 8.2.0（Docker 容器运行中） |
| Docker | 29.5.3 |

### 2.2 端口规划

| 端口 | 服务 | 说明 |
|------|------|------|
| 18888 | OpenClaw | 已有 |
| 8443 | NewAPI | 已有 |
| 10809 | Xray | 已有 |
| 34634 | 宝塔面板 | 已有 |
| **8200** | **FundAdvisor 后端** | **本项目新增** |
| **8201** | **FundAdvisor 前端** | **本项目新增** |

### 2.3 前置依赖

- MySQL 8.0+ 运行中（已有 Docker 容器）
- Python 3.12+（已通过 pyenv 安装 3.12.9，`backend/.venv` 虚拟环境）
- Node.js 18+（当前 v24.16.0 已满足）
- NewAPI 中转站运行中（端口 8443）
- 网络可访问 `fund.eastmoney.com`（东方财富 API）

---

## 3. LLM 后端说明

### 3.1 中转架构

```
前端/后端 -> NewAPI(:8443/v1) -> NVIDIA NIM 免费渠道
```

### 3.2 主模型

| 模型 ID（NewAPI 字段） | 简称 | 用途 |
|------------------------|------|------|
| `stepfun-ai/step-3.7-flash` | step-3.7 | 日常 AI 分析（温度 0.3，超时 120s） |
| `minimaxai/minimax-m3` | minimax-m3 | advisor_service 中的 fallback 模型 |
| `nvidia/nvidia-nemotron-nano-9b-v2` | nemotron-9b | 二级 fallback |

> API Key 复用 BiliBot 的 NewAPI Token。

---

## 5. 核心架构

```
+-----------------------------------------------------------+
|                        用户交互层                            |
|        手机浏览器(PC兼容) -> Vue3 前端(响应式 + PWA)          |
+--------------------------+--------------------------------+
                           |  HTTP REST API (JSON)
                           v
+-----------------------------------------------------------+
|                        后端服务层                            |
|                    FastAPI(Python 3.12+)                    |
|  +-----------+  +-----------+  +-----------------+          |
|  | 持仓管理API |  | 净值爬虫   |  | AI 决策引擎(新增) |          |
|  | 收益分析API |  | 快照服务   |  | 邮件推送          |          |
|  +-----------+  +-----------+  +-----------------+          |
|  +-----------------------------+                            |
|  | APScheduler(净值抓取/快照/NAV回填)|                       |
|  +-----------------------------+                            |
+--------------------------+--------------------------------+
                           |
          +----------------+----------------+
          v                v                v
   +---------+    +---------+    +-----------+
   | MySQL   |    | NewAPI  |    | 东方财富API |
   |fund_advisor| |(:8443/v1)|   | (免费)     |
   +---------+    +---------+    +-----------+
```

### 技术栈总览

| 层 | 技术选型 | 版本 |667|
|----|----------|------|----|
| 前端框架 | Vue 3 (Composition API) | 3.x |
| UI 组件库 | Element Plus | 最新稳定版 |
| 图表库 | ECharts | 5.x |
| 构建工具 | Vite | 6.x |
| 前端路由 | Vue Router | 4.x |
| HTTP 客户端(JS) | Axios | 1.x |
| 后端框架 | FastAPI | 0.115.6 |
| Python | CPython | 3.12+ |
| ORM | SQLAlchemy | 2.0.36 (同步引擎) |
| 数据库迁移 | Alembic | 1.14.1 |
| 定时任务 | APScheduler | 3.10.4 |
| 数据处理 | pandas + openpyxl | 2.2.3 / 3.1.5 |
| HTTP 客户端(Py) | httpx | 0.28.1 |
| 设置管理 | pydantic-settings | 2.7.1 |
| 文件上传 | python-multipart | 0.0.20 |
| 数据库 | MySQL | 8.0+ |
| LLM 网关 | NewAPI | 自建 端口 8443 |
| PWA | Vite PWA Plugin | 待集成 |

### 关键架构决策

- **同步 SQLAlchemy 引擎**：使用 `create_engine` + `SessionLocal`（同步），数据库操作均为同步调用
- **Pydantic v2**：Settings 通过 `pydantic-settings` 从 `.env` 文件加载配置
- **路由前缀**：所有 API 统一挂在 `/api` 下，如 `/api/dashboard/summary`
- **模型关联**：Fund 与 FundHolding 通过 `fund_code` 字段应用层关联（非外键）
- **调度器**：APScheduler 嵌入 FastAPI 进程内，非独立 worker
- ** lifespan 管理**：通过 FastAPI lifespan 上下文管理器处理启动建表、调度器启停、后台 NAV 回填

---

## 4. 用户需求

1. **手机端 Web 访问**：随时随地查看持仓、收到 AI 建议，无需安装 App
2. **动态持仓识别**：自动识别盈亏状况、当前估值、持仓健康度
3. **智能投资建议**：结合市场方向和多方面因素，给出加仓/补仓/减仓建议
4. **辅助盈利决策**：通过数据分析和 AI 洞察，辅助卖出时机判断
5. **手动持仓录入**：不依赖 Excel 导出，支持单条新增/编辑/删除

---

## 6. 数据库设计

> 数据库名：`fund_advisor`，字符集 `utf8mb4`

### 6.1 表结构总览

共 7 张表：

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `funds` | 基金基础信息 | fund_code(唯一), latest_nav, nav_change_pct |
| `fund_holdings` | 持仓明细 | fund_code, platform, shares, cost_nav, status |
| `fund_nav_history` | 基金净值历史 | fund_code + nav_date(唯一约束) |
| `portfolio_snapshots` | 组合每日快照 | snapshot_date(唯一), total_market_value, portfolio_nav |
| `holding_changes` | 每次导入的持仓变动 | import_id, change_type(new/increase/decrease/clear) |
| `holding_daily_pnl` | 每日单持仓盈亏 | holding_id + pnl_date(唯一约束) |
| `import_records` | Excel 导入历史 | file_hash(防重复), total_rows, status |

### 6.2 详细字段定义

#### 6.2.1 funds（基金基础信息）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | |
| fund_code | VARCHAR(10) | NOT NULL, UNIQUE | 基金代码 |
| fund_name | VARCHAR(200) | NOT NULL | 基金名称 |
| fund_type | VARCHAR(50) | NULL | 基金类型 |
| management_company | VARCHAR(100) | NULL | 基金公司 |
| latest_nav | DECIMAL(10,4) | NULL | 最新净值(缓存) |
| latest_nav_date | DATE | NULL | 最新净值日期 |
| nav_change_pct | DECIMAL(8,4) | NULL | 最新涨跌幅% |
| status | SMALLINT | DEFAULT 1 | 1=启用 |
| created_at | DATETIME | DEFAULT NOW() | |
| updated_at | DATETIME | DEFAULT NOW() ON UPDATE NOW() | |

#### 6.2.2 fund_holdings（持仓明细）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | |
| fund_code | VARCHAR(10) | NOT NULL | 基金代码 |
| fund_name | VARCHAR(200) | NOT NULL | 基金名称 |
| share_type | VARCHAR(20) | DEFAULT '前收费' | 份额类别 |
| management_company | VARCHAR(100) | NULL | 基金公司 |
| platform | VARCHAR(100) | NOT NULL | 销售机构 |
| fund_account | VARCHAR(50) | NOT NULL | 基金账户 |
| trade_account | VARCHAR(50) | NOT NULL | 交易账户 |
| shares | DECIMAL(16,4) | NOT NULL | 持有份额 |
| share_date | DATE | NOT NULL | 份额日期 |
| nav_on_import | DECIMAL(10,4) | NULL | 导入时净值 |
| nav_date | DATE | NULL | 净值日期 |
| cost_nav | DECIMAL(10,4) | NULL | 持仓成本净值(可编辑) |
| market_value | DECIMAL(16,4) | NULL | 市值 |
| currency | VARCHAR(10) | DEFAULT '人民币' | |
| dividend_mode | VARCHAR(20) | NULL | 分红方式 |
| last_import_id | BIGINT | NULL | 关联导入记录 |
| status | SMALLINT | DEFAULT 1 | 1=持有 0=已清仓 |
| created_at | DATETIME | DEFAULT NOW() | |
| updated_at | DATETIME | DEFAULT NOW() ON UPDATE NOW() | |

> 唯一约束：`(fund_code, platform, fund_account, trade_account)` 名为 `uk_holding`

#### 6.2.3 fund_nav_history（净值历史）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK | |
| fund_code | VARCHAR(10) | NOT NULL | |
| nav_date | DATE | NOT NULL | |
| unit_nav | DECIMAL(10,4) | NOT NULL | 单位净值 |
| acc_nav | DECIMAL(10,4) | NULL | 累计净值 |
| change_pct | DECIMAL(8,4) | NULL | 涨跌幅% |
| created_at | DATETIME | DEFAULT NOW() | |

> 唯一约束：`(fund_code, nav_date)` 名为 `uk_fund_nav_date`

#### 6.2.4 portfolio_snapshots（组合快照）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK | |
| snapshot_date | DATE | NOT NULL, UNIQUE | |
| total_market_value | DECIMAL(16,4) | NOT NULL | |
| total_shares_count | INT | NOT NULL | |
| daily_pnl | DECIMAL(16,4) | NULL | |
| daily_pnl_pct | DECIMAL(8,4) | NULL | |
| platform_breakdown | JSON | NULL | 按平台市值分布 |
| holdings_detail | JSON | NULL | 全量持仓明细快照 |
| portfolio_nav | DECIMAL(12,6) | NULL | 组合净值(起始1.000000) |
| total_units | DECIMAL(20,4) | NULL | 组合份额 |
| net_inflow | DECIMAL(16,4) | NULL | 当日净资金流入 |
| created_at | DATETIME | DEFAULT NOW() | |

#### 6.2.5 holding_changes（持仓变动记录）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK | |
| import_id | BIGINT | NOT NULL | 关联 import_records.id |
| holding_id | BIGINT | NULL | 关联 fund_holdings.id |
| fund_code | VARCHAR(10) | NOT NULL | |
| fund_name | VARCHAR(200) | NULL | |
| platform | VARCHAR(100) | NULL | |
| change_type | VARCHAR(20) | NOT NULL | new/increase/decrease/clear |
| shares_before | DECIMAL(16,4) | NULL | |
| shares_after | DECIMAL(16,4) | NULL | |
| shares_delta | DECIMAL(16,4) | NULL | |
| nav_at_change | DECIMAL(10,4) | NULL | |
| mv_before | DECIMAL(16,4) | NULL | |
| mv_after | DECIMAL(16,4) | NULL | |
| created_at | DATETIME | DEFAULT NOW() | |

> 索引：`idx_hc_import_id(import_id)`, `idx_hc_fund_code(fund_code)`

#### 6.2.6 holding_daily_pnl（每日单持仓盈亏）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK | |
| pnl_date | DATE | NOT NULL | |
| holding_id | BIGINT | NOT NULL | |
| fund_code | VARCHAR(10) | NOT NULL | |
| shares | DECIMAL(16,4) | NULL | |
| nav | DECIMAL(10,4) | NULL | |
| prev_nav | DECIMAL(10,4) | NULL | |
| market_value | DECIMAL(16,4) | NULL | |
| daily_pnl | DECIMAL(16,4) | NULL | 日盈亏额 |
| daily_pnl_pct | DECIMAL(8,4) | NULL | 日盈亏率% |
| created_at | DATETIME | DEFAULT NOW() | |

#### 6.2.7 holding_daily_pnl（每日单持仓盈亏）续

> 唯一约束：`(holding_id, pnl_date)` 名为 `uk_holding_pnl_date`
> 索引：`idx_pnl_date(pnl_date)`, `idx_pnl_fund_code(fund_code)`

#### 6.2.8 import_records（导入记录）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK | |
| file_name | VARCHAR(255) | NOT NULL | |
| file_hash | VARCHAR(64) | NULL | SHA256 防重复 |
| total_rows | INT | DEFAULT 0 | |
| new_holdings | INT | DEFAULT 0 | |
| updated_holdings | INT | DEFAULT 0 | |
| removed_holdings | INT | DEFAULT 0 | |
| error_rows | INT | DEFAULT 0 | |
| data_date | DATE | NULL | |
| status | VARCHAR(20) | DEFAULT 'success' | |
| error_message | TEXT | NULL | |
| created_at | DATETIME | DEFAULT NOW() | |

---

## 7. 后端 API 完整规格

> 所有 API 前缀：`/api`  
> 数据格式：JSON  
> 认证：当前无认证（未来可加）

### 7.1 Dashboard 仪表盘 (`/api/dashboard`)

| 方法 | 路径 | 请求参数 | 响应 | 说明 |
|------|------|----------|------|------|
| GET | `/summary` | - | `DashboardSummary` | 总资产/日涨跌/持仓数/基金数/平台数/净值更新时间 |
| GET | `/platform-distribution` | - | `PlatformDistribution[]` | 按平台市值分布(含百分比/日盈亏) |
| GET | `/daily-pnl` | `days`(int, 默认30, 1-365) | `DailyPnLPoint[]` | 每日组合盈亏趋势(取自快照表) |
| GET | `/top-holdings` | `limit`(int, 默认10, 1-50) | `TopHolding[]` | 按市值排序的TOP持仓 |
| POST | `/backfill-portfolio-nav` | - | `{status: "ok"}` | 回填所有快照的组合净值 |

**DashboardSummary 结构：**
```json
{
  "total_market_value": "533018.0000",
  "daily_pnl": "1234.5600",
  "daily_pnl_pct": "0.2300",
  "total_holdings": 15,
  "total_funds": 8,
  "total_platforms": 3,
  "nav_update_time": "2026-07-28"
}
```

**PlatformDistribution 结构：**
```json
{
  "platform": "蚂蚁财富",
  "market_value": "200000.0000",
  "count": 5,
  "percentage": 37.52,
  "daily_pnl": "500.0000"
}
```

**DailyPnLPoint 结构：**
```json
{
  "date": "2026-07-28",
  "total_market_value": "533018.0000",
  "daily_pnl": "1234.5600",
  "daily_pnl_pct": "0.2300",
  "portfolio_nav": 1.023456,
  "cumulative_return_pct": 2.3456
}
```

**TopHolding 结构：**
```json
{
  "fund_code": "110011",
  "fund_name": "易方达中小盘混合",
  "total_market_value": "150000.0000",
  "total_shares": "50000.0000",
  "latest_nav": 3.0000,
  "nav_change_pct": 0.5600,
  "platform_count": 2
}
```

### 7.2 Funds 基金详情 (`/api/funds`)

| 方法 | 路径 | 请求参数 | 响应 | 说明 |
|------|------|----------|------|------|
| GET | `/{fund_code}` | 路径参数 fund_code | `FundDetailResponse` | 基金详情(含持仓汇总) |
| GET | `/{fund_code}/nav-history` | `days`(int, 默认90, 1-365) | `[{nav_date, unit_nav, acc_nav, change_pct}]` | 净值历史 |

**FundDetailResponse 结构：**
```json
{
  "id": 1,
  "fund_code": "110011",
  "fund_name": "易方达中小盘混合",
  "fund_type": "混合型",
  "management_company": "易方达基金",
  "latest_nav": 3.0000,
  "latest_nav_date": "2026-07-28",
  "nav_change_pct": 0.5600,
  "status": 1,
  "created_at": "2026-07-20T10:00:00",
  "updated_at": "2026-07-28T15:30:00",
  "total_shares": "50000.0000",
  "total_market_value": "150000.0000",
  "platform_count": 2
}
```

### 7.3 Holdings 持仓管理 (`/api/holdings`)

| 方法 | 路径 | 请求参数 | 响应 | 说明 |
|------|------|----------|------|------|
| GET | `` | `platform`(可选), `search`(可选), `sort_by`(默认market_value), `sort_order`(默认desc) | `HoldingResponse[]` | 持仓列表(支持筛选/排序) |
| POST | `` | Body: `HoldingCreate` | `HoldingResponse` (201) | 创建手动持仓（自动补充 fund 表记录）|
| GET | `/by-platform` | - | `HoldingsByPlatformResponse[]` | 按平台分组列出持仓 |
| GET | `/platforms` | - | `string[]` | 所有平台名称列表 |
| PATCH | `/{holding_id}` | Body: `{cost_nav: float}` | `HoldingResponse` | 更新持仓成本净值 |
| DELETE | `/{holding_id}` | - | `{status: "deleted", id: int}` (200) | 软删除持仓（status=0）|

**HoldingResponse 结构：**
```json
{
  "id": 1,
  "fund_code": "110011",
  "fund_name": "易方达中小盘混合",
  "platform": "蚂蚁财富",
  "fund_account": "xxx",
  "trade_account": "xxx",
  "shares": "50000.0000",
  "share_date": "2026-07-20",
  "cost_nav": 2.5000,
  "market_value": 150000.0000,
  "current_mv": 150000.0000,
  "daily_pnl": 840.0000,
  "total_pnl": 25000.0000,
  "latest_nav": 3.0000,
  "nav_change_pct": 0.5600
}
```

**HoldingsByPlatformResponse 结构：**
```json
{
  "platform": "蚂蚁财富",
  "holdings": [HoldingResponse, ...],
  "total_market_value": 200000.0000
}
```

### 7.4 Imports 导入管理 (`/api/imports`)

| 方法 | 路径 | 请求参数 | 响应 | 说明 |
|------|------|----------|------|------|
| POST | `/upload` | multipart/form-data: `file` | `ImportResult` | 上传Excel/ZIP导入持仓 |
| GET | `/history` | - | `ImportHistoryItem[]` | 导入历史 |
| GET | `/{import_id}/changes` | 路径参数 import_id | `HoldingChangeResponse[]` | 某次导入的持仓变动明细 |

**ImportResult 结构：**
```json
{
  "id": 1,
  "file_name": "export.xlsx",
  "total_rows": 15,
  "new_holdings": 3,
  "updated_holdings": 10,
  "removed_holdings": 0,
  "error_rows": 0,
  "data_date": "2026-07-28",
  "status": "success"
}
```

### 7.5 NAV 净值维护 (`/api/nav`)

| 方法 | 路径 | 请求参数 | 响应 | 说明 |
|------|------|----------|------|------|
| POST | `/refresh` | `smart`(bool, 默认true) | `{updated: int, skipped: int}` | 手动触发净值更新 |
| GET | `/status` | - | `{last_update, pending_count}` | 净值更新状态 |
| POST | `/snapshot` | - | `{snapshot_date, total_market_value, portfolio_nav}` | 手动创建今日快照 |
| POST | `/backfill-history` | - | `{fetched: int, failed: int}` | 回填所有持仓基金的历史净值 |
| POST | `/backfill-snapshots` | - | `{created: int}` | 从导入记录回填历史快照 |
| POST | `/backfill-holding-pnl` | - | `{dates_processed: int}` | 回填单持仓每日盈亏 |
| POST | `/backfill-all-daily-snapshots` | - | `{created_or_updated: int}` | 为所有NAV交易日创建/更新快照 |

### 7.6 Analysis 收益分析 (`/api/analysis`)

| 方法 | 路径 | 请求参数 | 响应 | 说明 |
|------|------|----------|------|------|
| GET | `/periods` | - | `PeriodItem[]` | 所有导入期间汇总 |
| GET | `/period-detail` | `start_date`(date), `end_date`(date) | `DailyPnLPoint[]` | 某期间每日盈亏明细 |
| GET | `/fund-pnl` | `start_date`(date), `end_date`(date) | `FundPnLSummary[]` | 某期间按基金汇总盈亏 |
| GET | `/calendar` | `year`(int), `month`(1-12) | `CalendarMonthResponse` | 月历收益数据 |
| GET | `/calendar/{target_date}/detail` | 路径参数 YYYY-MM-DD | `CalendarDayResponse` | 某日完整详情(汇总/各账户/交易/各持仓盈亏) |

**CalendarMonthResponse 结构：**
```json
{
  "year": 2026,
  "month": 7,
  "days": [
    {"date": "2026-07-01", "daily_pnl": 100.00, "daily_pnl_pct": 0.02, "is_trading_day": true},
    ...
  ],
  "month_summary": {"total_pnl": 5000.00, "trading_days": 20}
}
```

**CalendarDayResponse 结构：**
```json
{
  "date": "2026-07-28",
  "summary": {"daily_pnl": 1234.56, "daily_pnl_pct": 0.23, "total_mv": 533018.00},
  "account_assets": [{"platform": "蚂蚁财富", "market_value": 200000.00}],
  "trades": [{"fund_code": "110011", "change_type": "increase", "shares_delta": 1000}],
  "holdings_pnl": [{"fund_code": "110011", "daily_pnl": 840.00}]
}
```

### 7.7 Health 健康检查

| 方法 | 路径 | 响应 | 说明 |
|------|------|------|------|
| GET | `/health` | `{status: "ok", version: "1.0.0"}` | 健康检查 |

---

## 8. 后端服务层完整规格

### 8.1 DashboardService (`dashboard_service.py`)

**职责**：为前端仪表盘提供聚合数据

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `get_summary()` | - | DashboardSummary | 遍历活跃持仓 JOIN funds，用 latest_nav * shares 计算市值；用 nav_change_pct 反推日盈亏；统计基金数/平台数 |
| `get_platform_distribution()` | - | PlatformDistribution[] | 按平台分组聚合市值/盈亏/数量，计算百分比 |
| `get_daily_pnl(days)` | int | DailyPnLPoint[] | 从 portfolio_snapshots 取最近N天快照，计算 cumulative_return_pct = (portfolio_nav - 1) * 100 |
| `get_top_holdings(limit)` | int | TopHolding[] | 按 fund_code 分组聚合市值，JOIN funds 获取最新净值 |

**市值计算公式**：`current_mv = shares * latest_nav`（若 latest_nav 为空则用 holding.market_value 兜底）

**日盈亏计算公式**：`daily_pnl = mv * nav_change_pct / (100 + nav_change_pct)`

### 8.2 FundService (`fund_service.py`)

**职责**：查询单只基金详情

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `get_fund_detail(fund_code)` | str | FundDetailResponse | 查 Fund 表获取基础信息，聚合 FundHolding 获取总份额/总市值/平台数；若 latest_nav 存在则重新计算总市值 |

### 8.3 HoldingService (`holding_service.py`)

**职责**：持仓查询与管理

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `get_holdings(platform, search, sort_by, sort_order)` | 可选筛选 | HoldingResponse[] | JOIN FundHolding + Fund，计算 current_mv/daily_pnl/total_pnl；支持按 market_value/shares/fund_code/fund_name/platform 排序 |
| `get_holdings_by_platform()` | - | HoldingsByPlatformResponse[] | 按平台分组，每组含持仓列表和总市值 |
| `get_platforms()` | - | string[] | SELECT DISTINCT platform FROM fund_holdings WHERE status=1 |
| `update_cost(holding_id, cost_nav)` | int, float | HoldingResponse | 更新指定持仓的 cost_nav 字段 |

### 8.4 ImportService (`import_service.py`)

**职责**：Excel/ZIP 文件导入持仓

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `import_file(file)` | UploadFile | ImportResult | 判断 xlsx/zip，分别调用单文件或批量导入；计算文件 SHA256 防重复 |
| `import_excel(file_bytes, filename)` | bytes, str | ImportResult | 调用 ExcelParser 解析，与现有持仓比对，记录 new/increase/decrease/clear 变动 |
| `import_zip(file_bytes)` | bytes | ImportResult | 遍历 ZIP 内所有 xlsx，逐个调用 import_excel，汇总结果 |
| `get_import_history()` | - | ImportHistoryItem[] | 查 import_records 表按时间倒序 |
| `get_import_changes(import_id)` | int | HoldingChangeResponse[] | 查 holding_changes 表 |

**导入比对逻辑**：
- 新基金/新账户组合 -> change_type = `new`
- 已有持仓份额增加 -> change_type = `increase`
- 已有持仓份额减少 -> change_type = `decrease`
- 已有持仓份额归零 -> change_type = `clear`，holding.status = 0

### 8.5 NavService (`nav_service.py`)

**职责**：基金净值获取与管理

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `refresh_all_nav(smart=False)` | - | dict | 遍历所有持仓 fund_code，调用 NavFetcher 获取最新净值，更新 Fund 表 |
| `refresh_all_nav_smart()` | - | dict | 智能模式：先获取最新交易日，然后后台补全缺失的历史日期净值 |
| `get_nav_history(fund_code, days)` | str, int | list | 从 fund_nav_history 表取最近N天净值记录 |
| `get_nav_status()` | - | dict | 查询最后净值更新时间和待更新基金数 |
| `backfill_history()` | - | dict | 从首次导入日起回填所有持仓基金的历史净值 |

### 8.6 NavFetcher (`nav_fetcher.py`)

**职责**：从东方财富 API 抓取基金净值

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `fetch_latest_nav(fund_code)` | str | dict | 请求东方财富 API 获取最新一条净值 |
| `fetch_nav_history(fund_code, start_date, end_date)` | str, date, date | list | 获取指定日期范围的历史净值 |

**东方财富 API 端点**：
- 最新净值：`fundgz.1234567.com.cn/js/{fund_code}.js`
- 历史净值：`api.fund.eastmoney.com/f10/lsjz` 带 callback 参数

**反爬处理**：设置 User-Agent、Referer 头，请求间隔 0.5 秒，并发数限制 5

### 8.7 SnapshotService (`snapshot_service.py`)

**职责**：组合每日快照与组合净值计算

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `create_daily_snapshot()` | - | PortfolioSnapshot | 遍历活跃持仓计算总市值/平台分布/持仓明细，存入 portfolio_snapshots；计算 daily_pnl 和 portfolio_nav |
| `backfill_portfolio_nav()` | - | None | 为所有已有快照回填 portfolio_nav 字段 |
| `backfill_historical_snapshots()` | - | int | 从 import_records 的 data_date 创建历史快照 |
| `backfill_holding_daily_pnl()` | - | int | 遍历 fund_nav_history 所有交易日，为每个持仓计算每日盈亏写入 holding_daily_pnl |
| `backfill_all_daily_snapshots()` | - | int | 为所有有 NAV 数据的交易日创建/更新快照，使用 shares * unit_nav 计算市值 |

**组合净值计算逻辑**：
1. 首次快照设 portfolio_nav = 1.000000，total_units = total_market_value
2. 后续快照：`portfolio_nav = prev_nav * (1 + daily_pnl_pct / 100)`
3. net_inflow 检测：通过对比前后持仓份额变化计算当日资金流入/流出

### 8.8 AnalysisService (`analysis_service.py`)

**职责**：收益分析报表数据

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `get_periods()` | - | PeriodItem[] | 从 import_records 获取各导入期间，计算每期汇总盈亏 |
| `get_period_detail(start, end)` | date, date | DailyPnLPoint[] | 从 holding_daily_pnl 聚合每日盈亏 |
| `get_fund_pnl(start, end)` | date, date | FundPnLSummary[] | 按基金汇总某期间的盈亏数据 |

### 8.9 CalendarService (`calendar_service.py`)

**职责**：收益日历数据

| 方法 | 输入 | 输出 | 核心逻辑 |
|------|------|------|----------|
| `get_monthly_pnl(year, month)` | int, int | CalendarMonthResponse | 遍历月内每天从 holding_daily_pnl 聚合，标记交易日 |
| `get_day_detail(target_date)` | date | CalendarDayResponse | 汇总：日盈亏汇总 + 各平台资产明细 + 当日交易记录 + 各持仓盈亏 |

### 8.10 ExcelParser (`excel_parser.py`)

**职责**：解析基金E账户导出的 Excel 文件

**解析规则**：
- 使用 openpyxl 读取 .xlsx 文件
- 识别表头行（包含"基金代码"等关键词）
- 按列映射：基金代码、基金名称、份额、净值、市值、平台、基金账户、交易账户等
- 支持多个 Sheet 页（不同平台）
- 输出标准化 dict 列表供 ImportService 使用

---

## 9. 前端设计规格

### 9.1 技术栈

| 项目 | 技术/版本 |
|------|----------|
| 框架 | Vue 3 (Composition API, `<script setup>`) |
| UI 库 | Element Plus |
| 图表 | ECharts 5 (vue-echarts 封装) |
| 路由 | Vue Router 4 (history 模式) |
| HTTP | Axios |
| 构建 | Vite 6 |
| 状态管理 | Pinia (待引入，当前无全局 store) |
| PWA | Vite PWA Plugin (待集成) |

### 9.2 全局样式与设计风格

**整体风格**：干净简洁的金融数据界面，优先移动端。

**配色方案**：
| 用途 | 颜色 |
|------|------|
| 主色 | Element Plus 默认蓝色 (#409EFF) |
| 涨色 | 红色 (#F56C6C) — 中国习惯红涨绿跌 |
| 跌色 | 绿色 (#67C23A) |
| 背景色 | #f5f7fa (浅灰) |
| 卡片背景 | #ffffff |
| 文字主色 | #303133 |
| 文字次色 | #909399 |

**响应式断点**：
- 手机：< 768px (默认优先)
- 平板：769px - 1024px
- PC：> 1024px

**字体**：系统默认无衬线字体栈，数字使用等宽数字字体

### 9.3 前端入口与路由

**main.js**：
- 创建 Vue app
- 注册 Element Plus (完整引入)
- 注册 ECharts (全局组件 `v-chart`)
- 挂载 router
- Pinia 待引入

**路由配置** (history 模式, base `/`):

| 路径 | 组件 | 名称 | 导航栏标题 |
|------|------|------|------------|
| `/` | DashboardView | dashboard | 仪表盘 |
| `/holdings` | HoldingsView | holdings | 持仓 |
| `/fund/:fundCode` | FundDetailView | fundDetail | 基金详情 |
| `/analysis` | AnalysisView | analysis | 收益分析 |
| `/calendar` | CalendarView | calendar | 收益日历 |
| `/import` | ImportView | import | 导入 |
| `/settings` | SettingsView | settings | 设置 |
| `/advisor` | AdvisorView | advisor | AI建议 |

### 9.4 App.vue 布局结构

**整体布局**：移动端底部导航栏式布局

```
+----------------------------------+
|         <router-view />           |  <- 主内容区，flex:1 出滚动
+----------------------------------+
| [仪表盘][持仓][分析][日历][设置]    |  <- 底部 TabBar，固定定位
+----------------------------------+
```

**TabBar 配置**：
- 5 个标签页：仪表盘 / 持仓 / 分析 / 日历 / 设置
- 图标使用 Element Plus Icon
- 当前路由高亮
- 导入页和基金详情页通过路由跳转，不显示在 TabBar 中

### 9.5 API 封装 (`api/index.js`)

使用 Axios 封装，baseURL 在 vite.config.js 中通过代理指向 `http://localhost:8200`

**封装方法**：
```javascript
import axios from 'axios'
const api = axios.create({ baseURL: '/api' })
export const dashboardAPI = {
  getSummary: () => api.get('/dashboard/summary'),
  getPlatformDist: () => api.get('/dashboard/platform-distribution'),
  getDailyPnl: (days=30) => api.get('/dashboard/daily-pnl', {params:{days}}),
  getTopHoldings: (limit=10) => api.get('/dashboard/top-holdings', {params:{limit}}),
}
export const holdingsAPI = { ... }
export const fundsAPI = { ... }
export const importAPI = { ... }
export const navAPI = { ... }
export const analysisAPI = { ... }
```

### 9.6 Vite 构建配置

```javascript
// vite.config.js 关键配置
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: { '/api': { target: 'http://localhost:8200', changeOrigin: true } }
  }
})
```

**Nginx 反代配置** (生产环境 `nginx.conf`):
- listen 80
- root /usr/share/nginx/html
- try_files $uri $uri/ /index.html (SPA history 模式 fallback)
- /api/ 反代到 backend:8200

---

## 10. 前端页面完整规格

### 10.1 DashboardView (仪表盘)

**路由**：`/`

**页面结构**：
```
+--------------------------------+
|  AssetSummaryCard              |  <- 总资产卡片
|  总资产 | 日涨跌 | 持仓数
+--------------------------------+
|  PortfolioNavChart             |  <- 组合净值曲线图
|  (ECharts 折线图, 30天)
+--------------------------------+
|  平台分布                       |  <- PlatformPieChart
|  (ECharts 饼图)
+--------------------------------+
|  TOP 持仓                       |  <- TopHoldings 列表
|  基金名称 | 市值 | 涨跌幅
+--------------------------------+
```

**数据源**：`/api/dashboard/summary` + `/api/dashboard/daily-pnl` + `/api/dashboard/platform-distribution` + `/api/dashboard/top-holdings`

**交互**：
- 点击 TOP 持仓项 -> 跳转 `/fund/:fundCode`
- ~~下拉刷新（移动端）~~ **未实现**

### 10.2 HoldingsView (持仓列表)

**路由**：`/holdings`

**页面结构**：
```
+--------------------------------+
|  搜索框 | 平台筛选下拉           |
+--------------------------------+
|  HoldingsTable                 |
|  基金代码 | 名称 | 平台
|  份额 | 最新净值 | 市值
|  日盈亏 | 总盈亏 | [编辑成本]
+--------------------------------+
```

**数据源**：`/api/holdings` + `/api/holdings/platforms`

**交互**：
- 搜索输入框：输入基金代码/名称模糊搜索
- 平台下拉：调用 `/api/holdings/platforms` 获取列表
- 表头点击排序：市值/份额/基金代码/基金名称/平台
- 点击行 -> 跳转基金详情
- 编辑成本按钮 -> 弹窗修改 cost_nav -> PATCH `/api/holdings/{id}`

### 10.3 FundDetailView (基金详情)

**路由**：`/fund/:fundCode`

**页面结构**：
```
+--------------------------------+
|  基金基础信息卡片               |
|  代码 | 名称 | 类型 | 基金公司
|  最新净值 | 涨跌幅
+--------------------------------+
|  持仓汇总                       |
|  总份额 | 总市值 | 平台数
+--------------------------------+
|  NavHistoryChart               |  <- 净值走势图
|  (ECharts 折线图, 90天)
+--------------------------------+
```

**数据源**：`/api/funds/{fund_code}` + `/api/funds/{fund_code}/nav-history?days=90`

### 10.4 ImportView (导入页)

**路由**：`/import`

**页面结构**：
```
+--------------------------------+
|  文件上传区域 (拖拽/点击)       |
+--------------------------------+
|  导入结果                       |
|  新增 X | 更新 X | 清仓 X
|  错误行 X
+--------------------------------+
|  导入历史列表                   |
|  文件名 | 日期 | 状态 | [查看变动]
+--------------------------------+
```

**数据源**：POST `/api/imports/upload` + GET `/api/imports/history` + GET `/api/imports/{id}/changes`

**交互**：
- el-upload 组件拖拽上传 Excel/ZIP
- 上传完成后显示 ImportResult
- 历史记录可展开查看 HoldingChange 详情

### 10.5 AnalysisView (收益分析)

**路由**：`/analysis`

**页面结构**：
```
+--------------------------------+
|  期间选择下拉                   |
|  (各导入期间)
+--------------------------------+
|  DailyPnLChart                 |  <- 日收益趋势图
|  (ECharts 柱状+折线组合图)
+--------------------------------+
|  基金盈亏排名                   |
|  基金名称 | 期间盈亏 | 盈亏率%
+--------------------------------+
```

**数据源**：`/api/analysis/periods` + `/api/analysis/period-detail` + `/api/analysis/fund-pnl`

### 10.6 CalendarView (收益日历)

**路由**：`/calendar`

**页面结构**：
```
+--------------------------------+
|  年月选择器                     |
+--------------------------------+
|  日历网格 (7列)                 |
|  每格显示日期 + 日盈亏额/率     |
|  红绿背景色标识涨跌
|  空白格为非交易日
+--------------------------------+
|  月度汇总                       |
|  总盈亏 | 交易日数 | 日均盈亏
+--------------------------------+
```

**数据源**：`/api/analysis/calendar?year=X&month=Y`

**交互**：
- 点击某日格子 -> 弹窗显示 CalendarDayResponse 详情
- 弹窗内容：summary + account_assets + trades + holdings_pnl
- 左右滑动切换月份

### 10.7 SettingsView (设置页)

**路由**：`/settings`

**页面结构**：
```
+--------------------------------+
|  净值更新                       |
|  [手动刷新净值] [历史回填]       |
|  最后更新时间: YYYY-MM-DD
+--------------------------------+
|  快照管理                       |
|  [创建今日快照] [回填历史快照]   |
|  [回填组合净值] [回填每日盈亏]   |
|  [回填所有日快照]
+--------------------------------+
|  显示设置 (待开发)               |
|  隐私开关 | 主题切换
+--------------------------------+
```

**数据源**：调用各 NAV 管理接口

### 10.8 AdvisorView (AI建议页)

**路由**：`/advisor`

**页面结构**：
```
+--------------------------------+
|  AI 顾问                       |
|  [AI已配置标签] [生成分析报告]   |
+--------------------------------+
|  市场环境分析卡片               |
|  趋势判断 | 总体判断 | 关键信号
+--------------------------------+
|  持仓健康度评估                 |
|  每只基金：健康分进度条(绿黄红)
+--------------------------------+
|  操作建议(时间线)               |
|  基金 | 操作(加/减/持/关) | 理由
+--------------------------------+
|  组合整体诊断                   |
|  集中度风险 | 调仓建议 | 整体评价
+--------------------------------+
```

**数据源**：`POST /api/advisor/analyze` + `GET /api/advisor/status`

**交互**：
- 点击「生成分析报告」按钮触发 POST /api/advisor/analyze
- 加载时显示骨架屏 (el-skeleton)
- 失败时显示警告提示 (el-alert)
- 各卡片展示结构化分析结果

---

## 11. 前端组件完整规格

### 11.1 AssetSummaryCard.vue

**用途**：仪表盘顶部资产概览卡片

**Props**:
| 名称 | 类型 | 说明 |
|------|------|------|
| summary | Object | DashboardSummary 数据 |

**展示内容**：总资产(大字号)、日涨跌额、日涨跌幅%、持仓数、基金数、平台数
**样式**：白色卡片背景，圆角，阴影；涨红跌绿；移动端全宽

### 11.2 PortfolioNavChart.vue

**用途**：组合净值走势折线图

**Props**:
| 名称 | 类型 | 说明 |
|------|------|------|
| data | Array | DailyPnLPoint[] |

**ECharts 配置**：
- 类型：折线图 (line)
- X轴：日期
- Y轴：组合净值 portfolio_nav + 累计收益率 cumulative_return_pct(双Y轴)
- 颜色：净值线蓝色，收益率线橙色
- tooltip：显示日期、净值、日盈亏、累计收益率
- 移动端：开启 dataZoom 缩放

### 11.3 PlatformPieChart.vue

**用途**：平台市值分布饼图

**Props**:
| 名称 | 类型 | 说明 |
|------|------|------|
| data | Array | PlatformDistribution[] |

**ECharts 配置**：
- 类型：饼图 (pie)，环形 (doughnut)
- radius: ['40%', '70%']
- 标签：平台名 + 百分比
- tooltip：显示市值、持仓数、日盈亏
- 颜色：自动多色

### 11.4 NavHistoryChart.vue

**用途**：基金净值历史走势图

**Props**:
| 名称 | 类型 | 说明 |
|------|------|------|
| data | Array | [{nav_date, unit_nav, acc_nav, change_pct}] |

**ECharts 配置**：
- 类型：折线图 (line) + 柱状图 (bar) 组合
- 折线：单位净值 unit_nav
- 柱状：涨跌幅 change_pct (双Y轴)
- tooltip：显示日期、净值、涨跌幅

### 11.5 HoldingsTable.vue

**用途**：持仓列表表格

**Props**:
| 名称 | 类型 | 说明 |
|------|------|------|
| holdings | Array | HoldingResponse[] |
| platforms | Array | string[] (平台列表) |

**Events**:
| 名称 | 参数 | 说明 |
|------|------|------|
| sort-change | {sort_by, sort_order} | 排序变更 |
| edit-cost | {id, cost_nav} | 编辑成本 |
| row-click | holding | 点击行跳转详情 |

**表格列**：基金代码 | 基金名称 | 平台 | 份额 | 最新净值 | 市值 | 日盈亏 | 总盈亏 | 操作
**移动端**：使用 el-table 的响应式或卡片列表替代

### 11.6 DailyPnLChart.vue

**用途**：日收益趋势图（分析页）

**Props**:
| 名称 | 类型 | 说明 |
|------|------|------|
| data | Array | DailyPnLPoint[] |

**ECharts 配置**：
- 类型：柱状图 (bar) + 折线图 (line) 组合
- 柱状：日盈亏额 daily_pnl (红涨绿跌)
- 折线：累计收益率
- tooltip：显示日期、日盈亏、日盈亏率、总市值

---

## 12. AI 决策引擎设计

> 核心新增模块，FundAdvisor 区别于原项目的主要价值

### 12.1 分析维度

#### 维度一：市场环境分析

- **大盘技术面**：均线系统(5/20/60/120日)、量价配合、趋势判断
- **板块轮动热度**：近期资金流向、领涨/领跌板块识别
- **宏观政策面**：LLM 对财经新闻摘要，提炼政策信号
- **市场情绪**：换手率变化、恐贪指数(Fear & Greed)

#### 维度二：持仓健康度评估

- **估值指标**：PE/PB 百分位(与历史对比判断高低)
- **风格漂移检测**：实际持仓与基金宣称风格的偏离度
- **基金经理变动**：任职时间、历史业绩稳定性
- **规模风险**：基金规模变化趋势，清盘预警(迷你基金识别)
- **回撤与波动率**：最大回撤、年化波动率、夏普比率

#### 维度三：加仓/减仓决策

| 场景 | 建议 |
|------|------|
| 低估值 + 基本面正向 | ✅ 推荐加仓，附建议金额区间 |
| 高估值 / 市场过热 | 🔴 建议减仓止盈，说明减仓比例 |
| 单个持仓占比过高 | ⚠️ 分散建议，提示集中度风险 |
| 持续跑输同类基准 | 🔄 建议换基，给出替代方向 |

#### 维度四：组合整体诊断

- 股债配比偏离度(与目标配置对比)
- 行业集中度风险(单一行业上限预警)
- 整体回撤范围评估
- 基金间相关性分析(避免同涨同跌)

### 12.2 分析触发机制

| 触发条件 | 类型 | 说明 |
|----------|------|------|
| OpenClaw cron 工作日 09:00 | 定时(晨间) | 生成完整分析报告，邮件推送 |
| 用户手动点击 | 即时 | 全量分析，Frontend 实时展示 |
| 净值更新后 | 轻量检查 | 仅更新关键指标，不生成完整报告 |

### 12.3 推送渠道

| 渠道 | 实现方式 | 说明 |
|------|----------|------|
| 邮件 | 复用 BiliBot SMTP 配置 -> QQ 邮箱 | 盘后分析报告 |
| Web 页面 | AdvisorView.vue | 即时查看，含图表 |

### 12.4 新增后端文件

| 文件 | 说明 |
|------|------|
| `backend/services/advisor_service.py` | AI 分析引擎核心：构建持仓上下文、构造 Prompt、调用 NewAPI、解析 JSON、错误降级 |
| `backend/services/mail_service.py` | SMTP 邮件推送：构建 HTML 报告、发送分析结果 |
| `backend/scheduler/advisor_job.py` | 定时任务模块：AI 分析 → 邮件推送工作流 |
| `backend/api/advisor.py` | `POST /api/advisor/analyze` + `GET /api/advisor/status` |
| `backend/api/scheduler.py` | `POST /api/scheduler/run-advisor` 手动触发调度 |
| `frontend/src/views/AdvisorView.vue` | AI 建议前端展示页：市场环境/持仓健康度/操作建议/组合诊断 |

### 12.5 新增 API 端点

| 方法 | 路径 | 请求参数 | 响应 | 说明 |
|------|------|----------|------|------|
| POST | `/api/advisor/analyze` | `model`(Query, 默认step-3.7-flash) | `AdvisorReport` | 触发全量 AI 分析 |
| GET | `/api/advisor/status` | - | `{configured, api_base, default_model}` | 检查 NewAPI 配置状态 |
| POST | `/api/scheduler/run-advisor` | `push_email`(bool, 默认true), `model`(str, 默认step-3.7-flash) | `{success, is_fallback, analysis, email_sent, summary}` | 手动触发 AI 分析 + 可选邮件推送 |

### 12.6 Prompt 设计要点

- 输入结构化(持仓数据 + 市场数据 + 估值数据)，避免自由文本导致输出不可控
- 输出格式固定(JSON Schema)，便于前端渲染
- 加入 few-shot 示例，提高建议质量一致性
- 温度参数：分析类任务 `temperature=0.2~0.3`，保证稳定性
- 模型选择：推荐 `stepfun-ai/step-3.7-flash` 做日常分析，`mistralai/mistral-large-3-675b` 做深度分析

### 12.7 AdvisorReport 响应结构 (JSON Schema)

```json
{
  "generated_at": "2026-07-29T18:49:19",
  "model": "stepfun-ai/step-3.7-flash",
  "portfolio_date": "2026-07-29",
  "market_analysis": {
    "trend": "震荡/上涨/下跌/震荡偏强/震荡偏弱",
    "key_signals": ["信号1", "信号2"],
    "overall": "简短的市场整体判断（30字以内）"
  },
  "holdings_health": [
    {
      "fund_code": "基金代码",
      "fund_name": "基金名称",
      "health_score": 0,
      "concerns": "主要风险",
      "suggestion": "处理建议"
    }
  ],
  "actions": [
    {
      "fund_code": "基金代码",
      "fund_name": "基金名称",
      "action": "hold/reduce/add/watch",
      "reason": "理由",
      "priority": "high/medium/low"
    }
  ],
  "portfolio_diagnosis": {
    "concentration_risk": "集中度风险描述",
    "rebalance_suggestion": "调仓建议",
    "overall_assessment": "整体评价"
  }
}
```

---

## 13. 定时任务与调度

### 13.1 APScheduler 内置任务 (`scheduler/jobs.py`)

| 任务名 | 触发时间 | 说明 |
|--------|----------|------|
| `job_daily_nav_refresh` | 每交易日 15:30 | 从东方财富抓取所有持仓基金最新净值 |
| `job_daily_snapshot` | 每交易日 16:00 | 创建当日组合快照 |
| `job_startup_nav_check` | 应用启动时 | 后台异步检查净值是否需要回填 |

**调度器配置**：
- APScheduler BlockingScheduler 嵌入 FastAPI lifespan
- 使用 AsyncIOScheduler
- 时区：Asia/Shanghai

### 13.2 OpenClaw cron 定时任务

| 任务名 | 时间 | 说明 |
|--------|------|------|
| FundAdvisor daily analysis push | 工作日 09:00 Asia/Shanghai (`0 9 * * 1-5`) | 调用 `POST /api/scheduler/run-advisor?push_email=true` 生成报告并邮件推送 |

---

## 14. Docker 部署详细规格

### 14.1 后端 Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ backend/
COPY alembic/ alembic/
COPY alembic.ini .
RUN mkdir -p data/uploads
EXPOSE 8200
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8200"]
```

**注意**：当前 Dockerfile EXPOSE 和 CMD 端口均已改为 8200

### 14.2 前端 Dockerfile

```dockerfile
FROM node:18-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### 14.3 前端 nginx.conf

```nginx
server {
    listen 80;
    location /api/ {
        proxy_pass http://backend:8200;
    }
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
}
```

### 14.4 docker-compose.yml (目标版本)

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8200:8200"
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    networks:
      - fund-net

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "8201:80"
    depends_on:
      - backend
    restart: unless-stopped
    networks:
      - fund-net

networks:
  fund-net:
    driver: bridge
```

**注意**：`docker-compose.yml.example` 仍为旧端口（8000/3000），使用前需手动改为 8200/8201

---

## 15. 环境变量完整参考

### 15.1 .env 配置文件

```env
# 数据库
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=<MySQL密码>
DB_NAME=fund_advisor

# 应用
APP_ENV=production
APP_PORT=8200

# 净值抓取
NAV_FETCH_CONCURRENCY=5
NAV_FETCH_INTERVAL=0.5

# NewAPI (LLM 网关)
NEWAPI_BASE_URL=http://127.0.0.1:8443/v1
NEWAPI_API_KEY=<复用BiliBot Token>

# SMTP (邮件推送)
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=<QQ邮箱>
SMTP_PASSWORD=<授权码>
SMTP_TO=<收件邮箱>
```

### 15.2 config.py Settings 字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| DB_HOST | str | "***REMOVED***" | MySQL 容器地址 |
| DB_PORT | int | 3306 | |
| DB_USER | str | "root" | |
| DB_PASSWORD | str | "***REMOVED***" | 宝塔 MySQL 密码 |
| DB_NAME | str | "fund_advisor" | |
| APP_ENV | str | "development" | |
| APP_PORT | int | 8200 | |
| NAV_FETCH_CONCURRENCY | int | 5 | |
| NAV_FETCH_INTERVAL | float | 0.5 | |
| NEWAPI_BASE_URL | str | "" | 由 .env 覆盖 |
| NEWAPI_API_KEY | SecretStr | "" | 由 .env 覆盖 |
| SMTP_HOST | str | "" | 由 .env 覆盖 |
| SMTP_PORT | int | 465 | |
| SMTP_USER | str | "" | 由 .env 覆盖 |
| SMTP_PASSWORD | SecretStr | "" | 由 .env 覆盖 |
| SMTP_TO | str | "" | 收件邮箱，由 .env 覆盖 |

> ⚠️ 敏感配置通过 .env 文件覆盖，config.py 默认值仅作为 fallback

### 15.3 alembic.ini 配置

```ini
[alembic]
script_location = alembic
sqlalchemy.url = mysql+pymysql://root:<password>@127.0.0.1:3306/fund_advisor?charset=utf8mb4
```

---

## 16. 功能清单与开发阶段

### 16.1 已有功能（原项目，代码已就绪）

- [x] 基金 E 账户 Excel 导入（支持 .xlsx 和 .zip 批量）
- [x] 每日净值自动抓取（东方财富 API）
- [x] 组合总览（总资产 / 总收益 / 日涨跌）
- [x] 持仓维度分析（按基金 / 平台 / 账户）
- [x] 收益日历（月历视图 + 日详情弹窗）
- [x] 定时快照（APScheduler 自动）
- [x] 组合净值计算（起始 1.0，复利累加）
- [x] 持仓变动记录（new/increase/decrease/clear）
- [x] 每日单持仓盈亏（holding_daily_pnl）
- [x] 历史数据回填工具（净值/快照/盈亏）
- [x] 持仓成本编辑（PATCH cost_nav）

### 16.2 需新增功能

| 优先级 | 功能 | 说明 |
|--------|------|------|
| P0 | 适配 qiqi 服务器部署 | 修改 config.py 默认值/端口/CORS/数据库名 |
| P0 | 货币基金净值 Bug 修复 | 万份收益 ≠ 单位净值，导致收益日历数据错误 |
| P0 | 收益数据一致性修复 | 日历每日收益 ≠ 仪表盘日涨跌，计算逻辑需统一 |
| P0 | 总资产统计偏差修复 | 资产字段被识别为字符串而非数值 (503,208 vs 533,018) |
| P1 | 手动持仓录入 | 不依赖 Excel 导出，支持单条新增/编辑/删除 |
| P1 | AI 决策引擎 | 对接 NewAPI，四大分析维度 |
| P1 | AdvisorView.vue | AI 建议前端展示页面 |
| P1 | OpenClaw cron 定时分析 | 工作日 09:00 触发 + 邮件推送 (已配置) |
| P1 | PWA 手机端优化 | Service Worker + 离线缓存 |
| P1 | 隐私开关 | 打开时展示金额和份额，关闭时仅显示百分比 |
| P3 | Backtrader 回测 | 验证 AI 建议质量 (Phase 4) |
| P3 | Prompt 自我优化 | 根据历史数据迭代 Prompt |
| P4 | 用户权限体系 | 多用户数据隔离 |

### 16.3 开发阶段

#### Phase 0 — 环境准备

- [x] 新建 MySQL 数据库 fund_advisor
- [x] 升级 Python 至 3.12+
- [x] 安装后端 pip 依赖
- [x] 安装前端 npm 依赖
- [x] 创建 .env 配置文件
- [x] 修改 config.py 默认值（DB_HOST/PORT/NAME/APP_PORT）
- [x] 修改 CORS 允许源（8201 端口）
- [x] 修改 Dockerfile/docker-compose 端口
- [x] 执行 alembic upgrade head
- [x] 启动验证：后端 :8200 + 前端 :8201

#### Phase 1 — 原项目适配

- [ ] 代码注释与文档统一中文
- [x] 新增手动持仓录入（API + 前端表单）
- [x] 修复货币基金净值 Bug
- [x] 修复收益数据不一致 Bug
- [x] 修复总资产统计偏差 Bug

#### Phase 2 — AI 决策引擎

- [x] 新增 advisor_service.py
- [x] 新增 api/advisor.py
- [x] 新增 mail_service.py
- [x] 新增 api/scheduler.py
- [x] 实现市场环境分析模块
- [x] 实现持仓健康度评估模块
- [x] 实现加仓/减仓决策模块
- [x] 实现组合整体诊断模块
- [x] 前端新增 AdvisorView.vue

#### Phase 3 — 自动化+推送

- [x] 配置 OpenClaw cron 定时任务
- [x] 接入邮件推送
- [ ] PWA 手机端优化

#### Phase 4 — 策略迭代

- [ ] Backtrader 回测框架
- [ ] 建议效果追踪
- [ ] 增加分析维度

---

## 17. 已知 Bug 与待修复项

### 17.1 货币基金净值 Bug (P0)

**现象**：货币基金的万份收益被当作单位净值使用，导致收益日历和快照数据错误
**根因**：东方财富 API 对货币基金返回的是万份收益而非单位净值，代码未做基金类型区分
**修复方向**：在 NavFetcher 中识别货币基金类型，进行万份收益到单位净值的转换

### 17.2 收益数据一致性 Bug (P0)

**现象**：收益日历每日收益 ≠ 仪表盘日涨跌
**根因**：日历数据来自 holding_daily_pnl 表，仪表盘来自 Fund.nav_change_pct 实时计算，两者计算路径不同
**修复方向**：统一数据来源，建议仪表盘也读取快照表数据

### 17.3 总资产统计偏差 Bug (P0)

**现象**：总资产显示 503,208，实际应为 533,018，偏差约 30,000
**根因**：Excel 解析时 asset 字段被识别为字符串而非数值，部分行市值未被正确累加
**修复方向**：在 excel_parser.py 中强制将市值字段转为 Decimal/float

### 17.4 config.py 默认值问题 (P0)

**现象**：config.py 中硬编码了原开发者的数据库地址(192.168.224.171:3326)和密码
**修复方向**：通过 .env 覆盖所有部署环境相关配置

### 17.5 CORS 配置问题 (P1)

**现象**：main.py 中 CORS 只允许 localhost:3000，部署后前端 8201 端口被拦截
**修复方向**：添加 `http://<server_ip>:8201` 或使用 `allow_origins=["*"]`

---

## 18. 服务汇总与外部依赖

| 服务 | 用途 | 费用 | 管理方式 |
|------|------|------|----------|
| 东方财富 API | 基金净值/走势数据 | 免费 | 原项目内置 |
| NewAPI 中转站 | LLM 分析引擎(NIM 渠道) | 零成本 | 自建(:8443) |
| QQ 邮箱 SMTP | 盘后分析报告推送 | 免费 | 复用 BiliBot 配置 |
| MySQL 8.0 | 数据持久化 | 已有容器 | Docker |

### 与 BiliBot 的协同

| 共享资源 | 说明 |
|----------|------|
| SMTP 配置 | 邮件推送共用 QQ 邮箱 |
| NewAPI Token | LLM 调用走同一中转站 |
| OpenClaw cron | 定时任务统一调度 |

---

## 19. 项目目录结构

```
fund-advisor/
├── backend/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── router.py              # 路由汇总, prefix=/api
│   │   ├── dashboard.py           # 仪表盘 API
│   │   ├── funds.py               # 基金详情 API
│   │   ├── holdings.py            # 持仓管理 API
│   │   ├── imports.py             # Excel 导入 API
│   │   ├── nav.py                 # 净值维护 API
│   │   ├── analysis.py            # 收益分析 API
│   │   ├── advisor.py             # AI 建议 API
│   │   └── scheduler.py           # 手动调度端点
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dashboard_service.py   # 仪表盘聚合
│   │   ├── fund_service.py        # 基金详情
│   │   ├── holding_service.py     # 持仓查询/管理
│   │   ├── import_service.py      # Excel 导入
│   │   ├── excel_parser.py        # Excel 解析
│   │   ├── nav_service.py         # 净值管理
│   │   ├── nav_fetcher.py         # 东方财富爬虫
│   │   ├── snapshot_service.py    # 快照/组合净值
│   │   ├── analysis_service.py    # 收益分析
│   │   ├── calendar_service.py    # 收益日历
│   │   ├── advisor_service.py     # AI 分析引擎
│   │   └── mail_service.py        # SMTP 邮件推送
│   ├── scheduler/                 # 定时任务
│   │   ├── __init__.py
│   │   ├── jobs.py               # APScheduler 净值/快照
│   │   └── advisor_job.py        # AI 分析+推送工作流
│   │   ├── __init__.py
│   │   ├── fund.py
│   │   ├── holding.py
│   │   ├── holding_change.py
│   │   ├── holding_daily_pnl.py
│   │   ├── nav_history.py
│   │   ├── portfolio_snapshot.py
│   │   └── import_record.py
│   ├── schemas/                   # Pydantic 请求/响应
│   │   ├── __init__.py
│   │   ├── dashboard.py
│   │   ├── fund.py
│   │   ├── holding.py
│   │   ├── holding_change.py
│   │   ├── holding_daily_pnl.py
│   │   ├── calendar.py
│   │   └── import_result.py
│   ├── models/                   # SQLAlchemy ORM 模型
│   │   ├── __init__.py
│   │   ├── fund.py
│   │   ├── holding.py
│   │   ├── holding_change.py
│   │   ├── holding_daily_pnl.py
│   │   ├── nav_history.py
│   │   ├── portfolio_snapshot.py
│   │   └── import_record.py
│   ├── config.py                 # Pydantic Settings
│   ├── database.py               # SQLAlchemy 引擎
│   ├── __init__.py
│   └── main.py                   # FastAPI 入口
├── frontend/
│   ├── src/
│   │   ├── api/index.js          # Axios 封装
│   │   ├── components/
│   │   │   ├── AssetSummaryCard.vue
│   │   │   ├── DailyPnLChart.vue
│   │   │   ├── HoldingsTable.vue
│   │   │   ├── NavHistoryChart.vue
│   │   │   ├── PlatformPieChart.vue
│   │   │   └── PortfolioNavChart.vue
│   │   ├── views/
│   │   │   ├── DashboardView.vue
│   │   │   ├── HoldingsView.vue
│   │   │   ├── FundDetailView.vue
│   │   │   ├── AnalysisView.vue
│   │   │   ├── CalendarView.vue
│   │   │   ├── ImportView.vue
│   │   │   ├── SettingsView.vue
│   │   │   └── AdvisorView.vue    # AI 建议页
│   │   ├── router/index.js
│   │   ├── App.vue
│   │   └── main.js
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── nginx.conf
│   ├── Dockerfile
│   └── .gitignore
├── alembic/
│   ├── env.py
│   ├── README
│   ├── script.py.mako
│   └── versions/
│       ├── f24fccd66eba_initial_tables.py
│       ├── 9c78e7c30ff5_add_holding_changes_holding_daily_pnl_.py
│       └── a1b2c3d4e5f6_add_portfolio_nav_to_snapshots.py
├── data/uploads/                  # Excel 上传临时目录
├── Dockerfile                     # 后端镜像
├── docker-compose.yml.example
├── .env.example
├── .gitignore
├── requirements.txt
└── PROJECT.md                     # 本文档
```
---

## 20. 风险提示

1. **非交易系统**：FundAdvisor 不是量化交易系统，不具备下单或调仓能力
2. **建议性质**：AI 分析建议仅供参考，不构成投资建议
3. **数据局限**：东方财富 API 可能存在延迟/缺失，系统有降级处理(人工提醒)
4. **LLM 局限**：大语言模型存在幻觉风险，建议结合专业研报参考
5. **账号安全**：Excel 文件和持仓数据为敏感信息，勿提交到公开仓库

---

## 附录 A：快速决策速查

| 场景 | 应对方式 |
|------|----------|
| 市场恐慌大跌 | 打开 AdvisorView -> 查看加仓建议 + 估值百分位 |
| 持仓持续亏损 | 检查健康度评估 -> 是否触发换基条件 |
| 收益达标想止盈 | 查看减仓建议 -> 参考建议比例分批卖出 |
| 加资金不知道买什么 | 查看组合诊断 -> 行业偏向 + 低估值基金推荐 |
| 盘后看今天总结 | 查收 15:30 邮件报告 / Web 端 Dashboard |

## 附录 B：常用命令速查

```bash
# 后端开发模式热重载
cd backend && uvicorn main:app --reload --port 8200

# 前端开发模式
cd frontend && npm run dev

# 数据库迁移
cd backend && alembic revision --autogenerate -m "描述" && alembic upgrade head

# 进入 MySQL 容器
docker exec -it <container_name> mysql -uroot -p

# 查看 OpenClaw cron 列表
openclaw cron list
```

## 附录 C：Alembic 迁移历史

| 版本 | 文件 | 内容 |
|------|------|------|
| f24fccd66eba | initial_tables.py | 初始表：funds, fund_holdings, fund_nav_history, portfolio_snapshots, import_records |
| 9c78e7c30ff5 | add_holding_changes_holding_daily_pnl_.py | 新增 holding_changes 和 holding_daily_pnl 表 |
| a1b2c3d4e5f6 | add_portfolio_nav_to_snapshots.py | portfolio_snapshots 新增 portfolio_nav, total_units, net_inflow 字段 |

## 附录 D：requirements.txt 完整依赖

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
sqlalchemy==2.0.36
pymysql==1.1.1
cryptography==44.0.0
alembic==1.14.1
openpyxl==3.1.5
pandas==2.2.3
httpx==0.28.1
apscheduler==3.10.4
pydantic==2.10.4
pydantic-settings==2.7.1
python-multipart==0.0.20
```

## 附录 E：前端 package.json 依赖

```
vue: ^3.x
vue-router: ^4.x
element-plus: latest
echarts: ^5.x
vue-echarts: latest
axios: ^1.x
vite: ^6.x
@vitejs/plugin-vue: latest
```

## 附录 F：部署检查清单

- [x] Python 3.12+ 已安装
- [x] MySQL fund_advisor 数据库已创建
- [x] .env 文件配置正确(DB_HOST/PORT/USER/PASSWORD/NAME)
- [x] config.py 默认值已被 .env 覆盖
- [x] CORS 允许前端 8201 端口
- [x] Dockerfile EXPOSE 改为 8200
- [x] docker-compose 端口改为 8200/8201
- [x] alembic upgrade head 执行成功
- [x] 后端 :8200 /health 返回 ok
- [x] 前端 :8201 正常加载
- [x] 前端 API 代理正常(/api -> :8200)
- [x] 东方财富 API 可访问
- [x] NewAPI :8443 可访问
- [x] SMTP 邮件配置成功
- [x] OpenClaw cron 已注册（工作日 09:00）
- [x] GitHub 已推送

---

## 22. 演进路线图

> 本路线图定义项目后续所有优化的分类层级和规划状态。每个需求标注层级、预估工作量和前置依赖。

### 22.1 层级定义

| 层级 | 说明 | 影响范围 | 回退复杂度 |
|------|------|----------|-----------|
| **L1 — 数据基础** | 增加输入数据维度，不改现有逻辑 | 仅后端新增/修改 | 低（单文件回滚） |
| **L2 — 流程优化** | 改变分析流程，不改 schema | 后端服务层 | 中（恢复旧方法） |
| **L3 — 架构演进** | 新增模块/表/前端页面 | 多文件跨层 | 高（数据库迁移） |

### 22.2 待优化项

| 编号 | 标题 | 层级 | 工作量 | 前置依赖 | 状态 | 备注 |
|------|------|------|--------|----------|------|------|
| OPT-001 | AI 分析增强：市场数据丰富 + 多模型共识 | L1+L2 | 中 | 无 | **规划中** | 见 RFC-001 |
| OPT-002 | AI 建议效果追踪（建议评分表 + 回溯） | L3 | 大 | OPT-001 | 待规划 | 需 DB migration |
| OPT-003 | PWA 离线缓存 + manifest | L1 | 小 | 无 | 待规划 | |
| OPT-004 | 隐私开关（金额/百分比切换） | L1 | 小 | 无 | 待规划 | |
| OPT-005 | 代码注释统一中文 | L1 | 小 | 无 | 待规划 | 纯代码风格 |
| OPT-006 | 前端持仓列表删除按钮 | L1 | 小 | 无 | ✅ 已完成 | |
| OPT-007 | PROJECT.md 核验修复 | L1 | 小 | 无 | ✅ 已完成 | |

### 22.3 历史演进

| 日期 | 内容 |
|------|------|
| 2026-07-29 | 建立演进路线图 §22 |
| 2026-07-29 | OPT-006/007 完成并标记 |

---

## 23. 项目目录说明

```
fund-advisor/
├── docs/           # 提案文件 (RFC-*.md)
│   └── ...         # 每次优化前先写 RFC 文档
├── backend/         # FastAPI 后端
├── frontend/        # Vue 3 前端
├── alembic/         # 数据库迁移
├── DEVLOG.md        # 开发日志（对话式）
├── CHANGELOG.md     # 版本变更摘要
├── PROJECT.md       # 本文件（完整项目文档）
└── README.md        # 项目简介（待创建）
```

---

*文档版本: v3.2 | 最后更新: 2026-07-29 | 变更: 新增 §22 演进路线图、§23 目录说明*

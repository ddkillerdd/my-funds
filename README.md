# my-funds — 基金投资分析 monorepo

一套**自托管、面向 AI 的基金投资分析系统**(monorepo),适合个人长期跟盘、用真实持仓做决策参考。分两个子项目:`fund-advisor`(线上应用)和 `fund-analyzer`(纯分析引擎)。

> ⚠️ **项目定位**：用于个人投资**决策辅助与学习**,不构成任何投资建议。基金有风险,入市需谨慎。

## ✨ 核心亮点

- **AI 深度分析报告**：每日定时(工作日)自动生成,含市场研判、持仓健康度打分、带**具体金额**的调仓建议、组合风险诊断,并推送到邮箱。
- **盘中择时**：拉取持仓基金跟踪指数的**实时快照**,当日判断涨跌方向与买卖点。
- **多模型 LLM 辩论**：分析引擎让多个模型各视角分析、交叉验证,降低单一模型幻觉(经 NewAPI 中转,模型可自配)。
- **组合回测**：多窗口(30/90/365 天)策略回测、每日盈亏曲线、优化建议。
- **引擎 / 应用分离**：纯计算引擎与 Web 应用解耦,引擎可独立单元测试。
- **自托管全栈**：FastAPI + Vue + MySQL,公网部署自理,数据不出服务器。

## 🖼 截图

> 待补充(GitHub 仓库可上传 `docs/screenshots/` 下的界面截图)。

## 📦 功能特性

| 能力 | 说明 |
|------|------|
| 每日 AI 分析报告 | 市场研判 + 持仓健康度 + 金额化调仓建议 + 组合诊断,邮件推送 |
| 盘中择时速览 | 持仓基金跟踪指数实时涨跌 + 5日线偏离 + 买卖点意见 |
| 持仓管理 | 导入真实持仓(快捷/Excel)、计算份额、市值、盈亏 |
| 投资分析 | 周期/持仓盈亏分析、收益日历、单基金净值历史 |
| 策略回测 | 任意基金多窗口回测、净值走势周期切换 |
| 自适应优化 | 依据历史信号自动优化目标波动率等参数 |
| 荐基/择时 | 筛选候选基金 + 入场时机判断 + 分批建仓计划(后端接口) |
| 定时推送 | 工作日自动分析 + 邮件(幂等去重,不重复骚扰) |

---

## 📁 仓库结构(more structure)

```
my-funds/                         # Git 仓库根 (origin: github.com/ddkillerdd/my-funds)
├── README.md                     # 本文档: monorepo 总览
├── fund-advisor/                 # 线上运行的应用 (被 workspace 软链, 实际跑着)
│   ├── backend/                  #   FastAPI 后端: services / api / models / scheduler
│   ├── frontend/                 #   Vite 前端
│   ├── PROJECT.md                #   项目完整文档 (部署/架构/DB/API规格)
│   ├── ARCHITECTURE.md           #   架构总览
│   ├── CHANGELOG.md / DEVLOG.md  #   变更记录 / 开发日志
│   └── docs/                     #   应用层 RFC (部署/持仓/回测学习)
└── fund-analyzer/                # 纯分析引擎 (库, 无 Web/ORM/API 依赖)
    ├── README.md                 #   引擎说明 (输入/输出/核心思路)
    ├── DESIGN.md                 #   设计文档 (方法论 + 架构 + Schema)
    ├── ARCHITECTURE.md           #   引擎架构总览
    ├── engine/                   #   17 个核心模块 (analyzer/decision/simulator/quant...)
    ├── tests/                    #   单元测试
    └── docs/                     #   引擎层 RFC (辩论/质量/荐基/择时/决策/模拟)
```

## 两个子项目的关系

```
fund-advisor (Web 应用, 调用方)         fund-analyzer (分析引擎, 库)
┌──────────────────────────┐            ┌────────────────────────┐
│ FastAPI :8200            │            │ Analyzer / Decision    │
│ Vite    :8201            │  import    │ Simulator / Screener   │
│ MySQL / 邮件 / 定时任务    └──────────► │ 量化层(32指标) → LLM    │
└──────────────────────────┘            └────────────────────────┘
       只负责 IO/调度/展示                    纯计算 + LLM, 可独立测试
```

- **fund-advisor** 依赖 **fund-analyzer**:分析内核由引擎提供,Web 层做数据抓取、持久化、定时推送、邮件。
- **fund-analyzer** 零 Web 依赖(仅 pandas/numpy/httpx),可脱离 Web 单独跑 `pytest tests/`。

> ⚠️ `fund-advisor` 是 `/root/.openclaw/workspace/fund-advisor` 的软链目标。改文件走 `my-funds/fund-advisor/` 或软链路径皆可(同一位置)。

## 核心能力速览

| 能力 | 位置 | 说明 |
|------|------|------|
| 持仓分析 | `fund-analyzer/engine/analyzer.py` | 32 量化指标 + 4视角 LLM 辩论 (RFC-005/006) |
| 荐基 (筛"买什么") | `engine/screener.py` | 基金筛选 (RFC-008) |
| 择时 (判"何时买") | `engine/timing.py` | 入场时机 (RFC-007) |
| 组合策略回测 | `engine/simulator.py` | Simulator/simulate() → BacktestReport (RFC-016) |
| Web API | `fund-advisor/backend/` | 45+ 端点, :8200 |
| 前端 | `fund-advisor/frontend/` | :8201 (Vite dev, 公网可达需自配域名/IP) |

## 文档导航

- **项目总览**: `fund-advisor/PROJECT.md` · `fund-advisor/ARCHITECTURE.md`
- **引擎设计**: `fund-analyzer/README.md` · `fund-analyzer/DESIGN.md` · `fund-analyzer/ARCHITECTURE.md`
- **RFC 索引**: `fund-analyzer/README.md` (引擎层 RFC-005~016) · `fund-advisor/docs/` (应用层 RFC-010~012)
- **决策引擎 RFC-014**(双项目共用): 唯一权威在 `fund-analyzer/docs/RFC-014-position-decision-engine.md`, fund-advisor 侧为软链引用。

## 运行

见 `fund-advisor/PROJECT.md` 部署章节。

---

## 🚀 快速开始

> 完整部署请见 [`fund-advisor/PROJECT.md`](fund-advisor/PROJECT.md)。以下为最小步骤概览。

**依赖**：Python 3.12 · Node 18+ · MySQL 8

```bash
# 1. 后端
cd fund-advisor
cp .env.example .env     # 填入你的 DB / NewAPI / SMTP 配置(见下)
pip install -r requirements.txt
# 初始化数据库表(alembic 或应用启动时自动建表)
alembic upgrade head
uvicorn backend.main:app --host 0.0.0.0 --port 8200

# 2. 前端(另开终端)
cd fund-advisor/frontend
npm install
npm run dev   # http://localhost:8201  (proxy 转发 /api 到 :8200)
```

也可以用 Docker:见 `fund-advisor/docker-compose.yml.example`。

## 🔐 环境变量(`fund-advisor/.env`)

| 变量 | 说明 |
|------|------|
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接 |
| `APP_ENV` / `APP_PORT` | 应用环境 / 端口 |
| `NAV_FETCH_CONCURRENCY` / `NAV_FETCH_INTERVAL` | 净值抓取并发 / 间隔 |
| `NEWAPI_BASE_URL` / `NEWAPI_API_KEY` | LLM 网关(OpenAI 兼容接口)地址与密钥 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_TO` | 邮件推送(SMTP) |

> 你的密钥只写在 `.env`,不要提交。`config.py` 中所有敏感项默认留空,由 `.env` 注入。

## 📄 License

[MIT](LICENSE)。

## ⚠️ 免责声明

本项目仅供**学习与个人决策辅助**使用,不构成任何投资建议或收益承诺。基金投资存在风险,请基于自身情况独立判断;因使用本项目产生的任何投资损失,作者不承担责任。


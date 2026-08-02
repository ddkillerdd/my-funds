# my-funds — 基金投资分析 monorepo

一套自托管的基金投资分析系统,分两个子项目:`fund-advisor`(线上应用)和 `fund-analyzer`(分析引擎)。单一 Git 仓库管理。

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
| 前端 | `fund-advisor/frontend/` | :8201 (公网 1.15.172.64:8201) |

## 文档导航

- **项目总览**: `fund-advisor/PROJECT.md` · `fund-advisor/ARCHITECTURE.md`
- **引擎设计**: `fund-analyzer/README.md` · `fund-analyzer/DESIGN.md` · `fund-analyzer/ARCHITECTURE.md`
- **RFC 索引**: `fund-analyzer/README.md` (引擎层 RFC-005~016) · `fund-advisor/docs/` (应用层 RFC-010~012)
- **决策引擎 RFC-014**(双项目共用): 唯一权威在 `fund-analyzer/docs/RFC-014-position-decision-engine.md`, fund-advisor 侧为软链引用。

## 运行

见 `fund-advisor/PROJECT.md` 部署章节。

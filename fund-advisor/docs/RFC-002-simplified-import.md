# RFC-002: 手动导入持仓精简 — 代码+金额两步导入

> **状态**: 实现中  
> **作者**: qiqi  
> **创建**: 2026-07-30  

## 动机

现有导入逻辑要求用户提供份额、净值、日期等大量字段，但用户从支付宝等平台只能看到 **持有金额**（市值）和基金代码。每次导入需要手动查净值算份额，体验差。

## 目标

支持用户**只填基金代码和持有金额**即可导入持仓，系统自动补全其余字段。

## 设计方案

### 导入流程

```
用户输入:
  基金代码  +  持有金额
      │
      ├── 查 funds 表 → 得 fund_name, latest_nav
      ├── 查 nav_history 表 → 得当日净值
      │
      ├── 有净值? ──→ 份额 = 金额 / 净值  (自动计算)
      │    ↓
      └── 无净值? ──→ 标记 "净值待采集", 
                       暂用 holding.shares = 0/无份额
                       等待下次 NAV 定时任务补采
```

### 后端改动

**新增 API** — `POST /api/holdings/simple-import`（无需 Excel 文件）：

```json
请求体:
{
  "records": [
    {
      "fund_code": "018044",        // 必填
      "market_value": 1.39,          // 必填
      "platform": "支付宝",          // 可选，默认 "支付宝"
      "share_date": "2026-07-30",   // 可选，默认今天
      "cost_nav": null               // 可选，默认从 latest_nav 取
    }
  ]
}
```

**导入服务层** `_fill_simple_holding()`:

1. 根据 `fund_code` 查 `funds` 表
   - 有记录 → 取 `latest_nav` 和 `fund_name`
   - 无记录 → 创建 fund 行（type=null，等定时任务补采 NAV 时再回填）
2. 查 `nav_history` 表最近的净值
   - 有净值 → 反算 `shares = market_value / nav`
   - 无净值 → shares=0，标记待补采集
3. 写入 `fund_holdings` 表（同现有 _merge_holdings 逻辑）

### 前端改动

**ImportView.vue 新增"快捷导入"卡片**:

```
┌─────────────────────────────────────┐
│  📝 快捷导入                          │
│                                      │
│  基金代码     持有金额                │
│  [018044    ] [1.39   ]  [+ 添加]   │
│                                      │
│  添加的基金列表:                       │
│  ┌─────────────────────────────┐    │
│  │ 018044 天弘纳斯达克100 C    │    │
│  │ 持有: 1.39元  → 自动计算    │    │
│  └─────────────────────────────┘    │
│                                      │
│  [批量导入]                          │
└─────────────────────────────────────┘
```

- 支持逐条添加（基金代码 + 持有金额）
- 添加时前端实时查询基金名称（可选，减轻后端压力）
- 批量提交导入

### 不影响现有流程

- 原有的 Excel/ZIP 导入完整保留
- 手动持仓录入（HoldingsView）也保留
- 仅新增 API + 前端新卡片，不修改任何现有路由/组件/API

## 实施计划

| Step | 内容 | 文件 |
|------|------|------|
| 1 | 新增 schema `SimpleImportRequest` / `SimpleImportRecord` | `backend/schemas/holding.py` |
| 2 | 新增 service 方法 `simple_import()` | `backend/services/holding_service.py` |
| 3 | 新增 API 端点 `POST /api/holdings/simple-import` | `backend/api/holdings.py` |
| 4 | 前端 ImportView.vue 新增"快捷导入"卡片 | `frontend/src/views/ImportView.vue` |
| 5 | 前端 api/index.js 新增 `simpleImport()` | `frontend/src/api/index.js` |

## 变更范围

- **仅新增代码**，不修改任何现有功能
- 新增文件：0 个
- 修改文件：5 个（schema + service + API + 前端 ×2）

## 注意事项

- 净值自动反算只在有 NAV 历史记录时生效
- 新基金（从未抓取过 NAV）会在下次定时任务（job_refresh_nav）后自动补全
- cost_nav 按导入时的最新净值填写，后续不会自动更新

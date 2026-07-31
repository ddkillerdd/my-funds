# AI 顾问报告持久化方案

## 目标
AI 投资顾问页面的分析报告刷新后不再丢失，用户可以随时查看最近一次分析的完整结果，
也可以浏览历史报告列表，点击任意查看。

## 实现

### 1. 数据库存储

新增表 `advisor_report`：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int (PK, auto) | 自增主键 |
| report_json | text | 完整分析报告 JSON |
| model_used | varchar(128) | 生成所用模型 |
| created_at | datetime | 生成时间 |

表由 `Base.metadata.create_all()` 自动创建，无需手动 migration。

### 2. API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/advisor/analyze` | 生成报告并写入 DB（原有逻辑，新增写入步骤） |
| GET | `/api/advisor/report` | 获取最近一次报告 |
| GET | `/api/advisor/report/{id}` | 获取指定 ID 的报告 |
| GET | `/api/advisor/reports` | 分页列出历史报告（仅元数据，不包含 JSON 正文） |
| GET | `/api/advisor/status` | 状态查询（新增 `has_report` / `last_report_at` 字段） |

`GET /api/advisor/reports` 参数：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| skip | int | 0 | 分页偏移 |
| limit | int | 20 | 每页数量（最大 100） |

返回示例：

```json
{
  "total": 5,
  "items": [
    {"id": 3, "model": "stepfun-ai/step-3.7-flash", "created_at": "2026-07-30T12:50:14"},
    {"id": 2, "model": "stepfun-ai/step-3.7-flash", "created_at": "2026-07-30T12:30:00"},
    ...
  ],
  "skip": 0,
  "limit": 20
}
```

### 3. 自动清理

- 每次写入新报告后检查总记录数
- 超过 `MAX_REPORTS`（默认 30）时，删除最旧的超量记录
- 保留最近 30 份报告，大约对应 1 个月的日常使用（每天生成约 1 次）

### 4. 前端

页面左侧为历史报告列表，右侧为报告内容。

`onMounted` 时：

1. 调 `GET /api/advisor/reports` 加载历史列表
2. 调 `GET /api/advisor/report` 加载最新报告
3. 调 `GET /api/advisor/status` 更新配置状态
4. 点击左侧任意历史条目加载对应报告
5. "加载更多"按钮分页追加

### 5. 配置

清理数量在 `backend/api/advisor.py` 的 `MAX_REPORTS = 30` 中定义，可直接改。
如在配置层增加选项，可移至 `.env` 的 `ADVISOR_MAX_REPORTS`。

## 文件变更

| 文件 | 变更 |
|------|------|
| `backend/models/advisor_report.py` | 新增 |
| `backend/api/advisor.py` | POST 写入 + 自动清理 + GET /report + GET /report/{id} + GET /reports |
| `frontend/src/views/AdvisorView.vue` | 左侧历史列表 + 点击浏览 + 分页加载 |
| `docs/report-persistence.md` | 本文档 |
| `DEVLOG.md` | 追加记录 |

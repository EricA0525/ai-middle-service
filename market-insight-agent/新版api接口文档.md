# Market Insight Agent Backend API（v0.2.0）

> 本文档基于当前 `backend/market_insight_agent/main.py` 实际路由整理。  
> 当前接口并非旧版 `/api/v1` 体系，实际前缀为 `/api` 与 `/api/v2`。

## 0. 给前端团队（必读）

- **推荐对接流**：`POST /api/v2/report-jobs`（创建）→ `GET /api/v2/report-jobs/{job_id}`（轮询）或 `.../events`（SSE）→ `GET /api/v2/report-jobs/{job_id}/result`（拿到 `report_id`）。
- **HTML 预览**：`GET /api/reports/{report_id}/html`（`text/html`，适合 iframe 直接展示）。
- **HTML 下载**：`GET /api/reports/{report_id}/download`（`FileResponse` 流式返回，带 `filename`，适合“下载报告”按钮）。
- **重要**：生成响应里的 `output_path` 是**后端服务器文件路径**（仅用于排障/运维），前端不要依赖它来读取文件；请统一使用上面的 `.../html` 与 `.../download`。

## 1. 基本信息

- **本地 Base URL**: `http://localhost:8000`
- **内容类型**: 默认 `application/json`
- **字符集**: `utf-8`
- **鉴权**: 支持 `X-API-Key`（当 `API_SECRET_KEY` 配置为空时自动关闭认证，便于本地开发）
- **命名风格**: 请求/响应字段以 `snake_case` 为主
  - 例：`report_id` / `use_llm` / `template_name`

## 2. 错误响应约定

业务错误（`AppError`）与限流错误采用双轨兼容结构：

```json
{
  "error": {
    "code": "JOB_QUEUE_FULL",
    "message": "任务队列已满（10/10），请稍后重试",
    "retriable": true,
    "retry_after_seconds": 30
  },
  "detail": "任务队列已满（10/10），请稍后重试"
}
```

- 前端优先读取 `error.message`，兼容旧逻辑可回退读取 `detail`。
- 若存在 `retry_after_seconds`，响应头会带 `Retry-After`。

常见状态码：

- `200`: 成功
- `401`: 认证失败（`X-API-Key` 缺失或无效）
- `429`: 速率限制/队列背压
- `404`: 资源不存在
- `409`: 任务状态未就绪（例如结果未完成）
- `413`: 请求体过大（超过服务端限制）
- `422`: 参数校验失败/质量闸门失败（v1/v2 都可能出现）
- `500`: 服务内部错误
- `504`: 同步等待超时（v1 兼容路径中）

说明：

- 部分端点在特定异常分支仍会返回 FastAPI 默认错误结构（仅 `{"detail":"..."}`）。
- 前端建议统一按优先级解析：`error.message` > `detail`。

---

## 3. 健康与运行状态

### 3.1 健康检查

- **GET** `/api/health`

响应示例：

```json
{
  "status": "healthy",
  "timestamp": "2026-02-09T18:00:00.000000"
}
```

### 3.2 LLM 状态

- **GET** `/api/llm/status`
- Query 参数：`do_web_search`（可选，`true/false`）

响应示例：

```json
{
  "ok": true,
  "base_url": "https://...",
  "model": "gpt-5.3-codex",
  "api_key_set": true,
  "ping": {
    "ok": true,
    "latency_ms": 1234,
    "reply": "pong",
    "error": null
  },
  "web_search": null
}
```

### 3.3 聚合运行状态（前端状态灯推荐）

- **GET** `/api/runtime/status`

响应示例：

```json
{
  "api": {
    "ok": true,
    "state": "online",
    "error": null,
    "latency_ms": null,
    "timestamp": "2026-02-09T18:00:00.000000"
  },
  "llm": {
    "ok": true,
    "state": "online",
    "error": null,
    "latency_ms": 1234,
    "timestamp": "2026-02-09T18:00:00.000000"
  }
}
```

---

## 4. 推荐对接路径：v2 异步任务（品牌健康度）

> **首选**：前端团队建议优先接 v2 作业接口。  
> 当前 `POST /api/v2/report-jobs` 仅支持 `report_type="brand_health"`。

### 4.0 对接流程（推荐实现）

1. 创建任务：`POST /api/v2/report-jobs` → 拿到 `job_id`  
2. 订阅进度（任选其一）：
   - 轮询：`GET /api/v2/report-jobs/{job_id}`（建议 1~3s 间隔，或按页面可见性降频）
   - SSE：`GET /api/v2/report-jobs/{job_id}/events`
3. 成功后取结果：`GET /api/v2/report-jobs/{job_id}/result` → 拿到 `report_id`
4. 展示/下载：
   - 预览：`GET /api/reports/{report_id}/html`
   - 下载：`GET /api/reports/{report_id}/download`

### 4.1 创建任务

- **POST** `/api/v2/report-jobs`
- 请求头（可选但推荐）：
  - `Idempotency-Key: <your-unique-key>`（仅该接口生效）
  - `X-API-Key: <secret>`（当服务开启鉴权时必填）

请求体：

```json
{
  "report_type": "brand_health",
  "brand_name": "索尼",
  "category": "耳机",
  "recommended_competitors": ["Bose", "森海塞尔"],
  "template_name": "海飞丝.html",
  "use_llm": true,
  "strict_llm": false,
  "enable_web_search": true
}
```

响应：

```json
{
  "job_id": "job-20260209180747-a95bd7b7",
  "report_type": "brand_health",
  "status": "queued",
  "created_at": "2026-02-09T18:07:47.237724"
}
```

幂等行为约定：
- 同 `Idempotency-Key` + 同请求体：返回同一个 `job_id`（幂等命中）。
- 同 `Idempotency-Key` + 不同请求体：返回 `409`，错误码 `JOB_IDEMPOTENCY_CONFLICT`。
- 默认幂等 TTL 为 `300s`（可由 `IDEMPOTENCY_TTL_SECONDS` 配置）。

### 4.2 查询任务状态

- **GET** `/api/v2/report-jobs/{job_id}`

响应字段（核心）：

- `status`: `queued | running | succeeded | failed | failed_quality_gate | cancelled`
- `current_stage`
- `progress`（`stage/completed_sections/total_sections`）
- `error_code` / `error_message`
- `section_logs[]`

### 4.3 SSE 订阅任务事件

- **GET** `/api/v2/report-jobs/{job_id}/events`
- 响应类型：`text/event-stream`

事件类型：

- `event: job_event`（阶段进度/日志）
- `event: job_terminal`（终态）
- 心跳：`: heartbeat`

事件示例（节选）：

```text
event: job_event
data: {"timestamp":"2026-02-09T18:10:00.000000","stage":"writer","level":"info","message":"开始章节生成与校验","data":{},"seq":12}

event: job_terminal
data: {"job_id":"job-...","status":"succeeded","finished_at":"2026-02-09T18:20:11.340639"}
```

说明：

- `job_event` 由编排器事件流直接透出，核心字段为 `timestamp/stage/level/message/data/seq`。
- `job_terminal` 不包含 `report_id`；终态后请调用 `GET /api/v2/report-jobs/{job_id}/result` 获取 `report_id`。

### 4.4 获取任务结果

- **GET** `/api/v2/report-jobs/{job_id}/result`
- 仅 `status=succeeded` 时返回 `200`，否则 `409`

响应示例：

```json
{
  "job_id": "job-...",
  "report_id": "索尼-20260209-xxxx",
  "output_path": ".../backend/output/索尼-20260209-xxxx.html",
  "generated_at": "2026-02-09T18:20:11.340639",
  "llm_diagnostics": {
    "sections": [],
    "ping": {},
    "search_meta": {},
    "error": null
  },
  "quality_gate": {}
}
```

`llm_diagnostics.sections[]` 诊断字段（可选）：

- `provider_error_type`：上游 LLM/网络错误类型（例如 `APITimeoutError`）
- `provider_error_message`：上游错误摘要（用于排障）
- `timeout_hit`：是否触发节级硬超时
- `fallback_reason`：兜底原因（如 `section_timeout` / `provider_error` / `validation_fail`）
- `search_degraded`：搜索是否降级继续（Tavily 异常或限额时为 `true`）

### 4.5 取消任务

- **POST** `/api/v2/report-jobs/{job_id}/cancel`

响应：

```json
{
  "job_id": "job-...",
  "cancelled": true
}
```

---

## 5. v1 兼容接口（可用但不推荐新增依赖）

### 5.1 品牌健康度（同步等待）

- **POST** `/api/generate/brand_health`

请求体：

```json
{
  "brand_name": "索尼",
  "category": "耳机",
  "recommended_competitors": ["Bose", "森海塞尔"],
  "template_name": "海飞丝.html",
  "use_llm": true,
  "strict_llm": false,
  "enable_web_search": true
}
```

响应（成功）：

```json
{
  "report_id": "索尼-20260209-xxxx",
  "report_type": "brand_health",
  "generated_at": "2026-02-09T18:20:11.340639",
  "output_path": ".../backend/output/索尼-20260209-xxxx.html",
  "inputs": {
    "brand_name": "索尼",
    "category": "耳机",
    "recommended_competitors": ["Bose", "森海塞尔"],
    "template_name": "海飞丝.html"
  },
  "llm": {
    "use_llm": true,
    "strict_llm": false,
    "enable_web_search": true,
    "ping": {},
    "search_meta": {},
    "error": null,
    "sections": []
  }
}
```

### 5.2 TikTok 社媒洞察（同步）

- **POST** `/api/generate/tiktok_social_insight`

请求体：

```json
{
  "category_name": "耳机",
  "product_selling_points": ["降噪", "舒适佩戴"],
  "template_name": "tiktok-toothpaste-report.html",
  "use_llm": true,
  "strict_llm": false,
  "enable_web_search": true
}
```

### 5.3 兼容别名

- **POST** `/api/generate`
- 等价于 `POST /api/generate/brand_health`

---

## 6. 报告资源接口

### 6.1 列表

- **GET** `/api/reports?limit=20`

响应：`ReportListItem[]`

```json
[
  {
    "report_id": "索尼-20260209-xxxx",
    "output_path": ".../backend/output/索尼-20260209-xxxx.html",
    "created_at": "2026-02-09T18:20:11.340639"
  }
]
```

### 6.2 元数据 + HTML 字符串

- **GET** `/api/reports/{report_id}`

响应示例：

```json
{
  "report_id": "索尼-20260209-xxxx",
  "output_path": ".../backend/output/索尼-20260209-xxxx.html",
  "html_content": "<!DOCTYPE html>..."
}
```

说明：

- `output_path` 为后端文件路径（仅用于排障/运维），前端请不要依赖它。
- `html_content` 可能很大；**前端展示建议使用** `/api/reports/{report_id}/html`（非 JSON 包裹，浏览器/iframe 直接渲染）。

### 6.3 仅 HTML（预览）

- **GET** `/api/reports/{report_id}/html`
- `Content-Type: text/html`

### 6.4 下载 HTML 文件

- **GET** `/api/reports/{report_id}/download`
- `Content-Type: text/html`
- `Content-Disposition: attachment; filename="{report_id}.html"`（浏览器将触发下载）

---

## 7. 模板管理接口（开发后台用）

### 7.1 模板状态
- **GET** `/api/template/status?template_name=海飞丝.html`

### 7.2 更新模板
- **POST** `/api/template/update`

```json
{
  "template_name": "海飞丝.html",
  "html_content": "<!DOCTYPE html>..."
}
```

### 7.3 获取模板原文
- **GET** `/api/template/content?template_name=海飞丝.html`

### 7.4 解析模板
- **POST** `/api/template/parse?template_name=海飞丝.html&force=false`

---

## 8. 前端团队对接建议

1. 新项目请直接使用 **v2 作业流**：创建任务 → 轮询/订阅事件 → 取结果。  
2. 页面状态灯使用 `/api/runtime/status`，不要高频调用重型接口。  
3. 报告渲染建议：
   - 在线预览：`/api/reports/{report_id}/html`（HTML 文本）
   - 下载导出：`/api/reports/{report_id}/download`
4. 错误处理优先读取 `error.message`，回退读取 `detail`；若有 `Retry-After` 则按秒重试。
5. 跨域对接（非同源）时，请在后端设置 `FRONTEND_URL` 为前端 Origin（例如 `https://your-frontend.example.com`），否则浏览器会因 CORS 拦截请求。

---

## 9. 版本与兼容说明

- 当前文档对应后端 FastAPI 版本 `0.2.0`。
- 旧版 `/api/v1` 文档（`旧版api接口文档.md`）与当前实现不兼容。

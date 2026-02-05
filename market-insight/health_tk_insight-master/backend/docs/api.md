# API 接口文档

## 概述

Market Insight Agent API 提供市场洞察报告自动生成服务。

**Base URL**: 

| 环境 | URL |
|------|-----|
| 本地开发 | `http://localhost:8000/api/v1` |
| 阿里云生产 | `https://{your-domain}/api/v1` |

> 💡 部署到阿里云后，将下文示例中的 `localhost:8000` 替换为实际域名即可。

**响应格式**: JSON（报告下载接口返回 HTML 文件流）

**通用响应结构**:
```json
{
    "success": true,
    "data": { ... }
}
```

**错误响应结构（统一封装）**:
```json
{
  "success": false,
  "data": {
    "error": "错误信息",
    "details": "可选详情"
  }
}
```

---

## 接口列表

### 1. 品牌健康度诊断

#### 1.1 提交分析任务

**POST** `/brand-health`

提交品牌健康度分析任务，返回任务 ID。

**请求体**:
```json
{
    "brand_name": "AOS",
    "competitors": ["BrandX", "BrandY"],
    "region": "中国大陆"
}
```

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| brand_name | string | ✅ | 品牌名称 |
| competitors | string[] | ❌ | 竞品列表 |
| region | string | ✅ | 目标地区 |

**响应**:
```json
{
    "success": true,
    "data": {
        "task_id": "task_abc123",
        "status": "processing"
    }
}
```

---

### 2. TikTok 社媒洞察

#### 2.1 提交分析任务

**POST** `/tiktok-insight`

提交 TikTok 社媒洞察分析任务。

**请求体**:
```json
{
    "category": "美妆",
    "selling_points": ["长效控油", "便携式设计"]
}
```

| 字段 | 类型 | 必填 | 描述 |
|------|------|------|------|
| category | string | ✅ | 商品品类 |
| selling_points | string[] | ✅ | 商品卖点 |

**响应**:
```json
{
    "success": true,
    "data": {
        "task_id": "task_xyz789",
        "status": "processing"
    }
}
```

---

### 3. 任务管理

#### 3.1 查询任务状态

**GET** `/tasks/{task_id}`

查询任务执行状态和结果。

**路径参数**:
| 参数 | 类型 | 描述 |
|------|------|------|
| task_id | string | 任务 ID |

**响应 (处理中)**:
```json
{
    "success": true,
    "data": {
        "task_id": "task_abc123",
        "status": "processing",
        "progress": 60,
        "message": "正在采集小红书数据..."
    }
}
```

**响应 (已完成)**:
```json
{
    "success": true,
    "data": {
        "task_id": "task_abc123",
        "status": "completed",
        "report_type": "brand_health",
        "report_url": "/api/v1/tasks/task_abc123/report",
        "created_at": "2026-02-02T12:00:00Z",
        "completed_at": "2026-02-02T12:02:15Z"
    }
}
```

**响应 (失败)**:
```json
{
    "success": false,
    "data": {
        "task_id": "task_abc123",
        "status": "failed",
        "error": "外部API调用失败",
        "details": "Tavily API 超时"
    }
}
```

---

#### 3.0 列出最近任务

**GET** `/tasks?limit=50`

返回最近任务列表（用于历史记录/管理台）。

**响应**:
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "task_id": "task_abc123",
        "task_type": "brand_health",
        "status": "completed",
        "progress": 100,
        "message": "报告渲染完成",
        "created_at": "2026-02-02T12:00:00Z",
        "completed_at": "2026-02-02T12:02:15Z",
        "report_url": "/api/v1/tasks/task_abc123/report"
      }
    ]
  }
}
```

---

#### 3.2 下载任务报告（HTML 文件流）

**GET** `/tasks/{task_id}/report`

获取任务生成的 HTML 报告文件流。

- 任务未完成：返回 409
- 任务失败：返回 400
- 成功：返回 `text/html`，并包含 `Content-Disposition`（浏览器可直接下载保存）

**响应 (成功)**:
- Content-Type: `text/html; charset=utf-8`
- Body: `<!DOCTYPE html>...`

## 状态码

| 状态码 | 描述 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在（如任务 ID 无效）|
| 500 | 服务器内部错误 |

---

## 使用示例

### cURL

```bash
# 1. 提交任务
curl -X POST http://localhost:8000/api/v1/brand-health \
  -H "Content-Type: application/json" \
  -d '{
    "brand_name": "AOS",
    "region": "中国大陆",
    "competitors": ["BrandX"]
  }'

# 2. 查询状态（轮询）
curl http://localhost:8000/api/v1/tasks/task_abc123

# 3. 下载报告（任务完成后）
curl -L http://localhost:8000/api/v1/tasks/task_abc123/report -o report.html
```

### Python

```python
import httpx
import time

async def generate_report():
    async with httpx.AsyncClient() as client:
        # 1. 提交任务
        response = await client.post(
            "http://localhost:8000/api/v1/brand-health",
            json={
                "brand_name": "AOS",
                "region": "中国大陆",
            },
        )
        task_id = response.json()["data"]["task_id"]
        
        # 2. 轮询状态
        while True:
            status_response = await client.get(
                f"http://localhost:8000/api/v1/tasks/{task_id}"
            )
            data = status_response.json()["data"]
            
            if data["status"] == "completed":
                report = await client.get(f"http://localhost:8000{data['report_url']}")
                return report.text
            elif data["status"] == "failed":
                raise Exception(data["error"])
            
            time.sleep(2)  # 等待 2 秒后重试
```

### JavaScript (前端)

```javascript
async function generateReport(brandName, region) {
  // 1. 提交任务
  const submitResponse = await fetch('/api/v1/brand-health', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      brand_name: brandName,
      region: region,
    }),
  });
  const { data: { task_id } } = await submitResponse.json();
  
  // 2. 轮询状态
  let interval = 2000; // 初始 2 秒
  while (true) {
    await new Promise(resolve => setTimeout(resolve, interval));
    
    const statusResponse = await fetch(`/api/v1/tasks/${task_id}`);
    const { data } = await statusResponse.json();
    
    if (data.status === 'completed') {
      const reportResp = await fetch(data.report_url);
      return await reportResp.text();
    } else if (data.status === 'failed') {
      throw new Error(data.error);
    }
    
    // 逐步增加轮询间隔
    interval = Math.min(interval + 1000, 5000);
  }
}
```

---

## 轮询建议

前端轮询任务状态时，建议：

1. **初始间隔**: 2 秒
2. **递增策略**: 2s → 3s → 5s
3. **最大间隔**: 5 秒
4. **超时时间**: 5 分钟

```javascript
const pollTask = async (taskId, maxWait = 300000) => {
  const startTime = Date.now();
  let interval = 2000;
  
  while (Date.now() - startTime < maxWait) {
    const response = await fetch(`/api/v1/tasks/${taskId}`);
    const { data } = await response.json();
    
    if (data.status !== 'processing') {
      return data;
    }
    
    await new Promise(r => setTimeout(r, interval));
    interval = Math.min(interval + 1000, 5000);
  }
  
  throw new Error('任务超时');
};
```

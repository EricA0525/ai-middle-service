# API 接口调用日志系统

## 概述

本项目为所有 FastAPI 应用添加了统一的 API 接口调用日志功能，用于追踪所有接口的调用情况，包括成功、失败和返回信息。

## 已实现的功能

### 1. 日志记录内容

每个 API 请求都会记录以下信息：

#### 请求信息

- **HTTP 方法**：GET、POST、PUT、PATCH、DELETE 等
- **请求路径**：完整的 URL 路径
- **查询参数**：URL 中的查询字符串参数
- **客户端 IP**：发起请求的客户端 IP 地址
- **User-Agent**：客户端浏览器或应用信息（market-insight）
- **请求体**：POST/PUT/PATCH 请求的请求体内容（JSON 格式）

#### 响应信息

- **响应状态码**：HTTP 状态码（200、404、500 等）
- **处理时间**：请求处理耗时（毫秒）
- **成功标志**：判断请求是否成功（2xx-3xx 为成功，4xx-5xx 为失败）

#### 错误信息

- **异常详情**：捕获并记录所有异常和错误堆栈
- **错误消息**：记录错误的详细描述

### 2. 日志级别

日志按照不同级别输出：

- **[INFO]**：请求开始和成功完成
- **[WARNING]**：请求失败（4xx、5xx 状态码）
- **[ERROR]**：请求处理过程中发生异常
- **[DEBUG]**：完整的请求详细信息（JSON 格式）

### 3. 日志示例

#### 成功的 GET 请求

[INFO] API Request Started | GET /health | Client: 192.168.1.100
[INFO] API Request Success | GET /health | Status: 200 | Time: 1.5ms
[DEBUG] Request Details: {"method": "GET", "path": "/health", "query_params": {}, "client_ip": "192.168.1.100", "process_time_ms": 1.5, "status_code": 200, "success": true}

#### 成功的 POST 请求（带请求体）

[INFO] API Request Started | POST /aigc/create | Client: 192.168.1.100
[INFO] API Request Success | POST /aigc/create | Status: 200 | Time: 125.3ms
[DEBUG] Request Details: {"method": "POST", "path": "/aigc/create", "query_params": {}, "client_ip": "192.168.1.100", "process_time_ms": 125.3, "request_body": {"prompt": "一个小男孩在街上跑步", "model_name": "Hailuo"}, "status_code": 200, "success": true}

#### 失败的请求

[INFO] API Request Started | GET /nonexistent | Client: 192.168.1.100
[WARNING] API Request Failed | GET /nonexistent | Status: 404 | Time: 0.8ms
[DEBUG] Request Details: {"method": "GET", "path": "/nonexistent", "query_params": {}, "client_ip": "192.168.1.100", "process_time_ms": 0.8, "status_code": 404, "success": false}

#### 异常请求

[INFO] API Request Started | POST /api/v1/tasks | Client: 192.168.1.100
[ERROR] API Request Exception | POST /api/v1/tasks | Error: Database connection failed
[ERROR] API Request Error | POST /api/v1/tasks | Error: Database connection failed | Time: 50.2ms

## 应用实现

### 1. Market Insight 应用

**位置**：`market-insight/health_tk_insight-master/backend/`

**实现方式**：

- 创建专门的中间件模块：`app/middleware/logging.py`
- 使用 `loguru` 库进行日志记录
- 在 `app/main.py` 中注册中间件

**文件变更**：

- ✅ `app/middleware/__init__.py`（新建）
- ✅ `app/middleware/logging.py`（新建）
- ✅ `app/main.py`（修改，添加中间件导入和注册）

### 2. AIGC Create 应用

**位置**：`aigc-create/`

**实现方式**：

- 在 `app.py` 中直接定义 `APILoggingMiddleware` 类
- 使用 Python 标准的 `print` 输出日志
- 在创建 FastAPI 应用后立即注册中间件

**文件变更**：

- ✅ `app.py`（修改，添加中间件类和注册）

### 3. TC API 应用

**位置**：`tc-api/`

**实现方式**：

- 在 `app.py` 中直接定义 `APILoggingMiddleware` 类
- 使用 Python 标准的 `print` 输出日志
- 在创建 FastAPI 应用后立即注册中间件

**文件变更**：

- ✅ `app.py`（修改，添加中间件类和注册）

## 使用说明

### 查看日志

#### 开发环境

日志会直接输出到控制台（stdout）。运行应用时可以直接看到：

```bash
# Market Insight
cd market-insight/health_tk_insight-master/backend
python -m uvicorn app.main:app --reload

# AIGC Create
cd aigc-create
uvicorn app:app --reload

# TC API
cd tc-api
uvicorn app:app --reload
```

#### 生产环境

对于 Market Insight 应用，可以通过环境变量配置日志文件：

```bash
export LOG_TO_FILE=true
export LOG_FILE_PATH=/var/log/market-insight/app.log
export LOG_LEVEL=INFO
```

对于 AIGC Create 和 TC API，建议使用进程管理工具（如 systemd、supervisor）将日志重定向到文件：

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 >> /var/log/app.log 2>&1
```

### 日志分析

#### 查找特定接口的调用

```bash
grep "GET /health" /var/log/app.log
```

#### 查找失败的请求

```bash
grep "\[WARNING\] API Request Failed" /var/log/app.log
grep "\[ERROR\]" /var/log/app.log
```

#### 查找慢请求（处理时间超过 1000ms）

```bash
grep -E "Time: [0-9]{4,}\.[0-9]+ms" /var/log/app.log
```

#### 统计接口调用次数

```bash
grep "API Request Started" /var/log/app.log | awk '{print $7}' | sort | uniq -c | sort -rn
```

## 技术实现

### 中间件工作原理

1. **请求拦截**：在请求到达路由处理函数之前拦截
2. **信息提取**：提取请求的各种元数据
3. **请求体读取**：对于 POST/PUT/PATCH 请求，读取并缓存请求体
4. **时间记录**：记录请求开始时间
5. **请求处理**：调用下一个中间件或路由处理函数
6. **响应记录**：记录响应状态码和处理时间
7. **异常捕获**：捕获并记录所有异常

### 关键技术点

#### 请求体读取和重建

```python
# 读取请求体
body = await request.body()

# 重建请求以便后续处理器可以读取
async def receive() -> Message:
    return {"type": "http.request", "body": body}

request._receive = receive
```

#### 处理时间计算

```python
start_time = time.time()
# ... 处理请求 ...
process_time = time.time() - start_time
process_time_ms = round(process_time * 1000, 2)
```

#### 成功/失败判断

```python
success = 200 <= response.status_code < 400
```

## 测试

运行测试脚本验证日志功能：

```bash
python test_logging_simple.py
```

测试覆盖：

- ✅ 成功的 GET 请求
- ✅ 成功的 POST 请求（带请求体）
- ✅ 失败的请求（400 错误）
- ✅ 404 错误
- ✅ 带查询参数的请求

## 扩展建议

### 1. 敏感数据脱敏

在 `logging.py` 中添加数据脱敏逻辑：

```python
def sanitize_data(data):
    """脱敏敏感数据"""
    if isinstance(data, dict):
        if "password" in data:
            data["password"] = "******"
        if "secret_key" in data:
            data["secret_key"] = "******"
    return data

# 在记录前脱敏
request_body = sanitize_data(request_body)
```

### 2. 结构化日志

使用 JSON 格式输出日志，便于日志收集系统（如 ELK）解析：

```python
import json
logger.info(json.dumps({
    "event": "api_request",
    "method": request.method,
    "path": request.url.path,
    "status": response.status_code,
    "duration_ms": process_time_ms,
    "timestamp": datetime.now().isoformat()
}))
```

### 3. 集成监控系统

将日志集成到监控系统（如 Prometheus、Grafana）：

```python
from prometheus_client import Counter, Histogram

request_counter = Counter('api_requests_total', 'Total API requests', ['method', 'path', 'status'])
request_duration = Histogram('api_request_duration_seconds', 'API request duration')

# 在中间件中记录指标
request_counter.labels(method=request.method, path=request.url.path, status=response.status_code).inc()
request_duration.observe(process_time)
```

## 维护建议

1. **定期清理日志文件**：使用 logrotate 或类似工具
2. **监控日志大小**：防止磁盘空间耗尽
3. **设置合适的日志级别**：生产环境建议使用 INFO 或 WARNING
4. **定期审查日志**：发现性能问题和异常模式

## 总结

本实现为所有 API 接口提供了完整的日志追踪能力，能够：

- ✅ 追踪所有接口调用
- ✅ 记录成功和失败的请求
- ✅ 记录请求和响应的详细信息
- ✅ 计算请求处理时间
- ✅ 捕获和记录异常

这为系统的监控、调试和性能优化提供了强有力的支持。

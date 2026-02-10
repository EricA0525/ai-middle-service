# AIGC视频生成服务 - 基于队列的架构

基于Redis Stream的分布式AIGC视频生成任务队列系统，支持动态并发控制和智能限流。

## 系统架构

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│             │     │             │     │             │
│  FastAPI    │────▶│   Redis     │◀────│   Worker    │
│    API      │     │   Stream    │     │  Consumer   │
│             │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
      │                    │                    │
      │                    │                    │
   POST /aigc/create   任务队列          调用腾讯云API
   GET /aigc/status    状态存储          动态并发控制
   GET /aigc/queue/info
```

## 核心特性

### 1. 任务队列系统
- **Redis Stream**: 高性能消息队列
- **消费者组**: 支持多Worker并发消费
- **任务状态**: 实时跟踪任务进度（queued/processing/completed/failed）

### 2. 动态并发控制
- **默认阈值**: 12个并发任务（可配置）
- **自动降级**: 遇到限流错误时自动降低阈值
- **自动恢复**: 无错误60秒后逐步恢复阈值
- **活跃计数**: 实时跟踪当前运行任务数

### 3. 智能错误处理
- **RequestLimitExceeded**: 自动降低并发阈值
- **其他错误**: 标记任务失败，继续处理下一个
- **错误恢复**: 定时检查并恢复阈值

## 快速开始

### 1. 环境准备

复制环境变量模板：
```bash
cp .env.example .env
```

编辑 `.env` 文件，填入腾讯云密钥：
```env
TENCENTCLOUD_SECRET_ID=your_secret_id_here
TENCENTCLOUD_SECRET_KEY=your_secret_key_here
```

### 2. 启动服务

**生产环境**：
```bash
docker-compose up -d
```

**开发环境**（带热重载）：
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

查看服务状态：
```bash
docker-compose ps
```

查看日志：
```bash
# API日志
docker-compose logs -f api

# Worker日志
docker-compose logs -f worker

# Redis日志
docker-compose logs -f redis
```

### 3. 测试API

#### 创建任务
```bash
curl -X POST http://localhost:8000/aigc/create \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "一个小男孩在街上跑步",
    "model_name": "Hailuo",
    "model_version": "2.3",
    "duration": 6,
    "resolution": "768P"
  }'
```

响应示例：
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "position": 1,
  "status": "queued"
}
```

#### 查询任务状态
```bash
curl http://localhost:8000/aigc/status/{task_id}
```

响应示例：
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "position": 0,
  "result": null
}
```

#### 查询队列信息
```bash
curl http://localhost:8000/aigc/queue/info
```

响应示例：
```json
{
  "queue_length": 3,
  "active_count": 2,
  "max_concurrency": 12
}
```

#### 健康检查
```bash
curl http://localhost:8000/health
```

## API文档

启动服务后，访问以下地址查看交互式API文档：

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `TENCENTCLOUD_SECRET_ID` | 腾讯云密钥ID | - |
| `TENCENTCLOUD_SECRET_KEY` | 腾讯云密钥Key | - |
| `VOD_SUBAPP_ID` | VOD子应用ID | 1320866336 |
| `REDIS_HOST` | Redis主机地址 | redis |
| `REDIS_PORT` | Redis端口 | 6379 |
| `REDIS_DB` | Redis数据库 | 0 |
| `DEFAULT_THRESHOLD` | 默认并发阈值 | 12 |
| `MAX_THRESHOLD` | 最大并发阈值 | 12 |
| `MIN_THRESHOLD` | 最小并发阈值 | 2 |
| `THRESHOLD_DECREASE` | 限流时降低值 | 2 |
| `THRESHOLD_INCREASE` | 恢复时增加值 | 1 |
| `RECOVERY_INTERVAL` | 阈值恢复间隔(秒) | 60 |
| `WORKER_POLL_INTERVAL` | Worker轮询间隔(秒) | 2 |
| `WORKER_BLOCK_TIME` | Redis阻塞时间(毫秒) | 5000 |

## 文件结构

```
aigc-create/
├── app.py                   # FastAPI应用（任务入队和查询）
├── worker.py                # Worker消费者（任务处理）
├── config.py                # 共享配置
├── requirements.txt         # Python依赖
├── Dockerfile              # Docker镜像构建
├── docker-compose.yml      # Docker编排配置（生产）
├── docker-compose.dev.yml  # Docker开发环境配置
├── .env.example            # 环境变量模板
├── .gitignore              # Git忽略文件
├── test_queue.py           # 队列系统测试
└── README.md               # 本文档
```

## Worker工作流程

```
┌─────────────────────────────────────────────────────┐
│  Worker循环                                          │
├─────────────────────────────────────────────────────┤
│  1. 从Redis Stream读取任务                           │
│  2. 检查active_count                                 │
│     ├─ < 阈值 → active_count+1 → 调用腾讯云          │
│     └─ >= 阈值 → 等待几秒再试                        │
│  3. 处理腾讯云响应：                                  │
│     ├─ 成功 → status=completed, active_count-1      │
│     ├─ RequestLimitExceeded:                        │
│     │   └─ 阈值-2, status=failed, active_count-1    │
│     └─ 其他错误 → status=failed, active_count-1     │
│  4. 阈值恢复：                                       │
│     └─ 60秒无错误 → 阈值+1（最高到最大值）           │
└─────────────────────────────────────────────────────┘
```

## 故障排查

### Redis连接失败
```bash
# 检查Redis是否运行
docker-compose ps redis

# 重启Redis
docker-compose restart redis
```

### Worker未消费任务
```bash
# 查看Worker日志
docker-compose logs -f worker

# 重启Worker
docker-compose restart worker
```

### 任务一直处于queued状态
```bash
# 检查活跃任务数和阈值
curl http://localhost:8000/aigc/queue/info

# 查看Worker是否运行
docker-compose ps worker
```

## 开发和测试

### 本地开发
```bash
# 安装依赖
pip install -r requirements.txt

# 启动Redis（使用Docker）
docker-compose up -d redis

# 运行API（开发模式）
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# 运行Worker（另一个终端）
python worker.py
```

### 运行测试
```bash
# 确保Redis运行
docker-compose up -d redis

# 运行队列系统测试
python test_queue.py
```

## 扩展性

### 横向扩展Worker
可以启动多个Worker实例来增加处理能力：

```bash
# 修改docker-compose.yml，添加更多worker实例
docker-compose up -d --scale worker=3
```

每个Worker需要设置不同的 `CONSUMER_NAME`。

### 监控和指标
建议添加以下监控：
- Redis Stream长度
- 活跃任务数
- 任务处理延迟
- 错误率和类型
- 阈值变化历史

## 许可证

MIT License

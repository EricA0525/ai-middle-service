# 开发指南

## 📋 目录

1. [项目架构](#项目架构)
2. [快速开始](#快速开始)
3. [开发规范](#开发规范)
4. [核心组件](#核心组件)
5. [添加新功能](#添加新功能)
6. [测试](#测试)
7. [部署](#部署)

---

## 项目架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                        │
│                        ↓ HTTP Request                           │
├─────────────────────────────────────────────────────────────────┤
│                      FastAPI Application                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ API Router  │→ │   Models    │→ │  Services   │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│         ↓                               ↓                        │
│  ┌─────────────────────────────────────────────────┐            │
│  │              Task Manager (Celery)               │            │
│  └─────────────────────────────────────────────────┘            │
│         ↓                                                        │
│  ┌─────────────────────────────────────────────────┐            │
│  │              LangGraph Agent                     │            │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────┐ │            │
│  │  │Template │→ │  Data   │→ │Content  │→ │Render│ │            │
│  │  │ Parser  │  │Collector│  │Generator│  │Report│ │            │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────┘ │            │
│  └─────────────────────────────────────────────────┘            │
│         ↓                    ↓                                   │
│  ┌──────────────┐    ┌──────────────┐                           │
│  │ Data Sources │    │     LLM      │                           │
│  │ - Tavily     │    │  (OpenAI)    │                           │
│  │ - 小红书     │    │              │                           │
│  │ - 抖音       │    │              │                           │
│  └──────────────┘    └──────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

### 目录结构说明

```
backend/
├── app/                    # 主应用
│   ├── api/               # API 层（接收请求、返回响应）
│   ├── models/            # 数据模型（Pydantic）
│   ├── services/          # 业务逻辑（任务管理）
│   ├── agents/            # LangGraph Agent（核心逻辑）
│   │   └── nodes/         # Agent 节点
│   ├── data_sources/      # 外部数据源客户端
│   ├── templates/         # HTML 报告模板
│   └── utils/             # 工具函数
├── tests/                  # 测试
└── docs/                   # 文档
```

---

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
cd d:/Project/health_tk_insight/backend

# 创建虚拟环境
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
copy .env.example .env

# 编辑 .env 文件，至少配置以下项：
# - LLM_API_KEY: LLM API 密钥
# - TAVILY_API_KEY: Tavily 搜索 API 密钥
# - TAVILY_CACHE_ENABLED / TAVILY_CACHE_TTL_SECONDS: Tavily 缓存开关与 TTL（秒）
# - TASK_STORE_BACKEND: memory | sqlite（如需任务持久化）
# - CELERY_ENABLED: true | false（如需 Celery 执行）
# - LOG_TO_FILE / LOG_FILE_PATH: 日志落盘
```

### 3. 启动服务

```bash
# 开发模式启动
uvicorn app.main:app --reload --port 8000

# 访问 API 文档
# http://localhost:8000/docs
```

### 4. 测试 API

```bash
# 提交品牌健康度分析任务
curl -X POST http://localhost:8000/api/v1/brand-health \
  -H "Content-Type: application/json" \
  -d '{"brand_name": "AOS", "region": "中国大陆"}'

# 查询任务状态
curl http://localhost:8000/api/v1/tasks/{task_id}

# 任务完成后下载 HTML 报告（文件流）
curl -L http://localhost:8000/api/v1/tasks/{task_id}/report -o report.html
```

---

## 可选：任务持久化（SQLite）

将 `.env` 中 `TASK_STORE_BACKEND=sqlite`，服务启动时会自动初始化 SQLite 表结构并将任务状态写入 `DATABASE_URL`。

---

## 可选：Celery + Redis

1) 启用：`.env` 中设置 `CELERY_ENABLED=true`，并确保 `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` 指向可用 Redis。

2) 启动 worker：

```bash
celery -A app.celery_app.celery_app worker --loglevel=info
```

3) 超时与重试：
- 任务执行超时由 `TASK_TIMEOUT_SECONDS` 控制（后端使用 `asyncio.wait_for`）
- Celery 任务默认自动重试（最多 3 次，指数退避）

---

## 开发规范

### 代码风格

1. **格式化**: 使用 `black` 格式化代码
2. **类型注解**: 所有函数必须有 Type Hints
3. **文档字符串**: 使用 Google 风格 docstring
4. **导入顺序**: stdlib → 第三方 → 本地

```python
# 示例
from typing import Dict, List, Optional  # stdlib

from fastapi import APIRouter  # 第三方
from loguru import logger

from app.models import Task  # 本地
```

### 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 模块 | snake_case | `task_manager.py` |
| 类 | PascalCase | `BrandHealthAgent` |
| 函数/变量 | snake_case | `create_task()` |
| 常量 | UPPER_SNAKE | `DEFAULT_TIMEOUT` |
| API 路径 | kebab-case | `/brand-health` |

### 日志规范

```python
from loguru import logger

# 使用适当的日志级别
logger.debug("详细调试信息")
logger.info("一般运行信息")
logger.warning("警告信息")
logger.error("错误信息")
logger.exception("异常信息（自动包含堆栈）")
```

---

## 核心组件

### 1. Task Manager

任务管理器负责任务的生命周期管理。

```python
from app.services.task_manager import task_manager

# 创建任务
task_id = await task_manager.create_task(
    task_type="brand_health",
    params={"brand_name": "AOS", "region": "中国"},
)

# 查询任务
task = await task_manager.get_task(task_id)

# 更新进度
await task_manager.update_task_progress(task_id, 50, "采集数据中...")

# 完成任务
```

await task_manager.complete_task(task_id, html_content)
```

说明：
- 任务状态查询接口 `GET /api/v1/tasks/{task_id}` 不再直接返回 `html_content`
- 前端应在状态为 `completed` 时读取 `report_url`，再请求 `GET /api/v1/tasks/{task_id}/report` 获取 HTML 文件流

### 2. LangGraph Agent

Agent 负责执行报告生成的核心逻辑。

```python
from app.agents import BrandHealthAgent

# 创建 Agent
agent = BrandHealthAgent(
    progress_callback=lambda p, m: print(f"{p}% - {m}")
)

# 执行
html_report = await agent.run({
    "brand_name": "AOS",
    "region": "中国大陆",
    "competitors": ["BrandX"],
})
```

### 3. Data Sources

数据源客户端负责从外部 API 获取数据。

```python
from app.data_sources import tavily_client

# 搜索
results = await tavily_client.search(
    query="AOS 品牌 市场分析",
    max_results=10,
)
```

---

## 添加新功能

### 添加新的 API 端点

1. 在 `app/api/v1/` 创建新文件：

```python
# app/api/v1/new_feature.py
from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def get_new_feature():
    return {"message": "Hello"}
```

2. 在 `router.py` 中注册：

```python
from app.api.v1 import new_feature

api_router.include_router(
    new_feature.router,
    prefix="/new-feature",
    tags=["新功能"],
)
```

### 添加新的数据源

1. 继承 `BaseDataSource`：

```python
# app/data_sources/new_source.py
from app.data_sources.base import BaseDataSource

class NewSourceClient(BaseDataSource):
    def __init__(self):
        super().__init__(name="new_source", ...)
    
    async def search(self, query: str, **kwargs):
        # 实现搜索逻辑
        pass
```

2. 在 `__init__.py` 中导出

### 添加新的 Agent 节点

1. 在 `app/agents/nodes/` 创建节点：

```python
# app/agents/nodes/new_node.py
class NewNode:
    async def __call__(self, state: Dict) -> Dict:
        # 节点逻辑
        return {**state, "new_data": result}
```

2. 在 Agent 的 `build_graph()` 中添加到工作流

---

## 测试

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定文件
pytest tests/test_api.py

# 运行带覆盖率
pytest --cov=app tests/
```

### 测试示例

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_create_brand_health_task():
    response = client.post(
        "/api/v1/brand-health",
        json={
            "brand_name": "TestBrand",
            "region": "中国大陆",
        },
    )
    assert response.status_code == 200
    assert "task_id" in response.json()["data"]
```

---

## 部署

### Docker 部署

```bash
# 构建镜像
docker build -t market-insight-agent .

# 运行容器
docker run -p 8000:8000 --env-file .env market-insight-agent
```

### 生产环境配置

```bash
# .env.production
APP_ENV=production
DEBUG=false
LOG_LEVEL=WARNING

# 使用 PostgreSQL
DATABASE_URL=postgresql://user:pass@host:5432/db

# 使用生产 Redis
REDIS_URL=redis://redis-host:6379/0
```

---

## 常见问题

### Q: 如何调试 Agent 执行流程？

设置 `LOG_LEVEL=DEBUG`，查看详细的节点执行日志。

### Q: 如何添加新的图表类型？

在 `app/utils/svg_generator.py` 中添加新的生成方法。

### Q: 数据源 API 不可用怎么办？

系统会自动使用模拟数据（开发模式），生产环境会使用 Tavily 作为降级方案。

---

## 联系

如有问题，请联系项目负责人或在项目仓库提交 Issue。

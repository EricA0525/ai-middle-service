# 开发任务清单 (TODO List)

## 📋 概述

本文档记录项目的待开发任务和进度。新窗口开发时请先阅读此文档了解当前状态。

**最后更新**: 2026-02-02  
**当前阶段**: 核心闭环已跑通，进入核心逻辑完善

---

## ✅ 已完成

### 项目基础设施
- [x] 项目目录结构创建
- [x] FastAPI 应用框架
- [x] 配置管理模块 (Pydantic Settings)
- [x] API 路由结构 (v1)
- [x] 数据模型定义 (Request/Response/Task)
- [x] 任务管理器框架 (内存存储版本)
- [x] Docker 配置
- [x] 开发文档和 API 文档

### LangGraph Agent 框架
- [x] BaseAgent 基类定义
- [x] BrandHealthAgent 框架
- [x] TikTokInsightAgent 框架
- [x] Agent 节点框架 (4个节点)
- [x] AgentState 状态定义

### 数据源框架
- [x] BaseDataSource 基类
- [x] TavilyClient 框架（带模拟数据）
- [x] XiaoHongShuClient 框架（带模拟数据）
- [x] DouyinClient 框架（带模拟数据）

### 工具类框架
- [x] SVGGenerator 框架（带占位实现）
- [x] HTMLRenderer 框架

### 模板
- [x] 品牌健康度 Jinja2 模板骨架
- [x] TikTok 洞察 Jinja2 模板骨架

---

## 🚧 进行中 / 待开发

### 高优先级 (P0) - 核心功能

#### 1. LangGraph 工作流实现
- [x] 安装并配置 LangGraph
- [x] 实现 BrandHealthAgent.build_graph()
- [x] 实现 TikTokInsightAgent.build_graph()
- [x] 添加节点间的状态传递逻辑

#### 2. 模板解析节点
- [x] 读取模板（当前解析 Jinja2 模板中的板块结构）
- [x] 使用 BeautifulSoup 解析 DOM
- [x] 提取报告板块结构（`.card[id]`）
- [x] 生成结构化模板骨架

#### 3. 数据采集节点
- [x] 对接真实 Tavily API（无 Key 时自动降级为 mock）
- [x] 实现搜索查询构建逻辑
- [x] 添加数据格式化处理（Tavily 字段统一）
- [x] 预留小红书/抖音 API 接口

#### 4. 内容生成节点
- [x] 设计 LLM 提示词模板（基础版）
- [x] 对接 OpenAI 兼容 API（无 Key 时自动降级为确定性内容）
- [x] 实现各板块内容生成
- [x] 添加基础内容质量校验（HTML 片段清洗：移除 script/style，抽取 body）

#### 5. 报告渲染节点
- [x] 完成 Jinja2 模板集成
- [x] 实现 SVG 图表生成（纯 SVG，无需 JS）
- [ ] 保持与参考模板一致的结构（CSS 已迁移，待补齐 DOM/布局细节）
- [x] 输出自包含 HTML

### 中优先级 (P1) - 增强功能

#### 6. Celery 任务队列
- [x] 配置 Celery + Redis（代码已支持，默认不启用）
- [x] 替换 BackgroundTasks 为 Celery（通过 `CELERY_ENABLED` 开关）
- [x] 实现任务进度追踪
- [x] 添加任务超时和重试（超时：`TASK_TIMEOUT_SECONDS`；Celery 自动重试）

#### 7. SVG 图表完善
- [x] 实现折线图生成
- [x] 实现柱状图生成
- [x] 实现雷达图生成
- [x] 实现环图生成
- [x] 实现散点图生成

#### 8. 数据持久化
- [x] 配置 SQLAlchemy（Async）
- [x] 创建任务状态表
- [x] 实现任务持久化存储（通过 `TASK_STORE_BACKEND=sqlite` 开关）
- [x] 添加历史记录查询（`GET /api/v1/tasks`）

### 低优先级 (P2) - 优化项

#### 9. 错误处理和降级
- [x] API 调用失败重试（数据源内置重试，Celery 任务自动重试）
- [x] 数据源降级策略（单数据源失败不影响整体，自动 fallback）
- [x] 统一异常处理（全局异常响应封装）
- [x] 错误日志收集（Loguru 文件落盘）

#### 10. 性能优化
- [x] 并行数据采集（asyncio.gather 并行采集各数据源）
- [x] 缓存机制（Tavily in-memory TTL 缓存）
- [x] 响应压缩（GZipMiddleware）

#### 11. 测试完善
- [ ] 单元测试覆盖
- [ ] 集成测试
- [ ] 端到端测试

---

## 📌 开发提示

### 新窗口开发指引

如果你是在新窗口继续开发，请按以下顺序：

1. **阅读产品设计文档**
   - `产品设计.md` - 了解产品需求和技术规格

2. **阅读架构文档**
   - `backend/README.md` - 项目结构概览
   - `backend/docs/development.md` - 开发指南
   - `backend/docs/architecture.md` - 架构决策记录

3. **查看参考模板**
   - `fake_brand_insight_report.html` - 品牌健康度报告参考
   - `tiktok-toothpaste-report.html` - TikTok 洞察报告参考

4. **开始开发**
   - 优先完成 P0 任务
   - 每完成一个任务，更新本清单

### 常用命令

```bash
# 进入后端目录
cd backend

# 启动开发服务器
uvicorn app.main:app --reload --port 8000

# 运行测试
pytest

# 格式化代码
black app/
```

### 文件修改提示

修改以下文件时需特别注意：

| 文件 | 注意事项 |
|------|---------|
| `app/config.py` | 配置项变更需同步更新 `.env.example` |
| `app/models/*.py` | 模型变更需更新 API 文档 |
| `app/agents/base.py` | AgentState 变更影响所有 Agent |
| `app/templates/*.html` | 保持与参考模板样式一致 |

---

## 📞 联系

如有疑问，请查阅产品设计文档或联系项目负责人。

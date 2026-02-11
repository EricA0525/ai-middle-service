# AIGC Video Generation Service

腾讯云VOD AIGC视频生成服务的Docker部署说明。

## 端口配置

为避免与 `market-insight` 服务冲突，本服务使用以下端口：

- **Redis**: `6380:6379` (对外端口6380，避免与market-insight的6379冲突)
- **API**: `8020:8000` (对外端口8020，避免与market-insight的8010冲突)

## 快速开始

### 1. 创建环境配置文件

复制 `.env.example` 创建 `.env` 文件：

```bash
cp .env.example .env
```

### 2. 配置腾讯云密钥

编辑 `.env` 文件，填入真实的腾讯云密钥：

```bash
vi .env
```

将以下两项替换为实际值：
- `TENCENTCLOUD_SECRET_ID=your_secret_id_here`
- `TENCENTCLOUD_SECRET_KEY=your_secret_key_here`

### 3. 启动服务

使用Docker Compose启动所有服务：

```bash
docker compose up -d --build
```

### 4. 验证服务

#### 查看容器状态
```bash
# 查看所有aigc相关容器
docker ps | grep aigc

# 应该看到三个容器：
# - aigc-redis
# - aigc-api
# - aigc-worker
```

#### 查看日志
```bash
# 查看API日志
docker logs aigc-api

# 查看Worker日志
docker logs aigc-worker

# 查看Redis日志
docker logs aigc-redis
```

#### 测试API
```bash
# 访问API文档（Swagger UI）
curl http://localhost:8020/docs

# 或在浏览器中访问
# http://localhost:8020/docs
```

## API 接口

服务提供以下接口：

- **POST /aigc/create** - 创建AIGC视频生成任务
- **POST /aigc/task** - 查询任务状态

详细的API文档可通过访问 `http://localhost:8020/docs` 查看。

## 停止服务

```bash
docker compose down
```

如需删除数据卷：

```bash
docker compose down -v
```

## 故障排查

### 端口冲突

如果遇到端口冲突，请检查：
1. market-insight 服务是否占用了 6379 或 8010 端口
2. 其他服务是否占用了 6380 或 8020 端口

### 容器无法启动

检查日志：
```bash
docker logs aigc-api
docker logs aigc-worker
```

常见问题：
- 检查 `.env` 文件是否存在且配置正确
- 检查腾讯云密钥是否有效
- 检查Docker守护进程是否正常运行

## 架构说明

本服务由三个容器组成：

1. **aigc-redis**: Redis数据库，用于缓存（预留用于未来的任务队列）
2. **aigc-api**: FastAPI应用，提供REST API接口
3. **aigc-worker**: Worker容器（预留用于未来的异步任务处理）

注意：当前版本的app.py未使用Celery，worker容器为预留配置。

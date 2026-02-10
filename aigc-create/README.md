# 腾讯云 AIGC 视频生成服务

本服务提供腾讯云 VOD AIGC 视频生成任务的创建和查询接口。

## 功能特性

- 创建 AIGC 视频生成任务（支持海螺、可灵等多种模型）
- 查询任务状态和详情
- 支持文生视频和图生视频

## 环境配置

### 1. 配置环境变量

复制 `.env.example` 文件为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写你的腾讯云密钥：

```bash
TENCENTCLOUD_SECRET_ID=your_secret_id_here
TENCENTCLOUD_SECRET_KEY=your_secret_key_here
```

**获取腾讯云密钥：**
访问 [腾讯云控制台 - API 密钥管理](https://console.cloud.tencent.com/cam/capi) 获取你的 SecretId 和 SecretKey。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

或手动安装：

```bash
pip install fastapi uvicorn pydantic tencentcloud-sdk-python
```

### 3. 启动服务

```bash
uvicorn app:app --reload --port 8000
```

服务将在 `http://localhost:8000` 启动。

## API 接口

### 1. 创建 AIGC 视频任务

**接口地址：** `POST /aigc/create`

**请求示例：**

```json
{
  "prompt": "一个小男孩在街上跑步",
  "model_name": "Hailuo",
  "model_version": "2.3",
  "duration": 6,
  "resolution": "768P",
  "aspect_ratio": "16:9",
  "enhance_prompt": "Enabled",
  "tasks_priority": 10
}
```

### 2. 查询任务详情

**接口地址：** `POST /aigc/task`

**请求示例：**

```json
{
  "task_id": "your_task_id_here"
}
```

## API 文档

启动服务后，访问以下地址查看交互式 API 文档：

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 常见问题

### 错误：Missing credentials

**原因：** 未正确配置环境变量 `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY`。

**解决方法：**
1. 确保已创建 `.env` 文件
2. 确保 `.env` 文件中包含有效的腾讯云密钥
3. 如果使用 Docker 或其他部署方式，确保环境变量已正确传递

### 如何获取 SubAppId？

SubAppId 已在代码中硬编码为 `1320866336`。如果需要使用其他子应用，请修改代码中的 `SubAppId` 值。

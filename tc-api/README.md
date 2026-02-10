# 腾讯云 API 包装服务

本服务提供腾讯云 VOD 上传和通用 API 调用的包装接口。

## 功能特性

- VOD 视频/封面上传
- 通用云 API 调用接口
- 健康检查接口

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
pip install fastapi uvicorn pydantic vod-python-sdk tencentcloud-sdk-python python-multipart
```

### 3. 启动服务

```bash
uvicorn app:app --reload --port 8001
```

服务将在 `http://localhost:8001` 启动。

## API 接口

### 1. 健康检查

**接口地址：** `GET /health`

**返回示例：**

```json
{
  "ok": true
}
```

### 2. VOD 视频上传

**接口地址：** `POST /vod/upload`

**请求参数：**
- `region` (表单): 地域，默认 "ap-guangzhou"
- `procedure` (表单，可选): 任务流
- `sub_app_id` (表单，可选): 子应用 ID
- `media` (文件): 媒体文件
- `cover` (文件，可选): 封面图片

**返回示例：**

```json
{
  "fileId": "xxx",
  "mediaUrl": "https://...",
  "coverUrl": "https://..."
}
```

### 3. 通用云 API 调用

**接口地址：** `POST /tencentcloud/call`

**请求示例：**

```json
{
  "service": "vod",
  "version": "2018-07-17",
  "action": "DescribeTaskDetail",
  "region": "ap-guangzhou",
  "params": {
    "TaskId": "xxx",
    "SubAppId": 1320866336
  }
}
```

## 常见问题

### 错误：Missing TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY

**原因：** 未正确配置环境变量 `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY`。

**解决方法：**
1. 确保已创建 `.env` 文件
2. 确保 `.env` 文件中包含有效的腾讯云密钥
3. 如果使用 Docker 或其他部署方式，确保环境变量已正确传递

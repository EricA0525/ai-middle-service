# 腾讯云API包装服务

本服务提供了腾讯云API的包装接口，包括VOD视频上传和通用云API调用功能。

## 功能特性

- VOD视频服务端上传
- 通用腾讯云API调用
- 支持多地域配置
- 自动化认证处理

## 环境要求

- Python 3.7+
- FastAPI
- 腾讯云Python SDK

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn vod-python-sdk tencentcloud-sdk-python
```

### 2. 配置环境变量

复制 `.env.example` 文件为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入您的腾讯云API密钥：

```bash
TENCENTCLOUD_SECRET_ID=your_actual_secret_id
TENCENTCLOUD_SECRET_KEY=your_actual_secret_key
```

**获取腾讯云API密钥的步骤：**

1. 登录 [腾讯云控制台](https://console.cloud.tencent.com/)
2. 点击右上角账号 -> 访问管理
3. 左侧菜单选择 "访问密钥" -> "API密钥管理"
4. 创建或查看现有密钥
5. 将 SecretId 和 SecretKey 复制到 `.env` 文件

⚠️ **安全提示**：
- 不要将 `.env` 文件提交到版本控制系统
- 不要在代码中硬编码密钥
- 定期更换API密钥
- 限制密钥权限范围

### 3. 启动服务

```bash
# 加载环境变量并启动服务
export $(cat .env | xargs) && uvicorn app:app --host 0.0.0.0 --port 8000
```

或者使用 python-dotenv：

```bash
pip install python-dotenv
# 然后在代码中添加 from dotenv import load_dotenv; load_dotenv()
```

### 4. 访问API文档

启动服务后，可以通过以下地址访问交互式API文档：

- Swagger UI: http://localhost:8000/docs

## API接口说明

### 1. 健康检查

**接口**: `GET /health`

**响应示例**:
```json
{
  "ok": true
}
```

### 2. VOD视频上传

**接口**: `POST /vod/upload`

**请求参数**:
- `region`: 地域，默认 "ap-guangzhou"
- `procedure`: 任务流（可选）
- `sub_app_id`: 子应用ID（可选）
- `media`: 媒体文件（必填）
- `cover`: 封面文件（可选）

### 3. 通用云API调用

**接口**: `POST /tencentcloud/call`

**请求示例**:
```json
{
  "service": "vod",
  "version": "2018-07-17",
  "action": "DescribeMediaInfos",
  "region": "ap-guangzhou",
  "params": {
    "FileIds": ["123456"]
  }
}
```

## 常见问题

### 错误: "Missing TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY"

**原因**: 未正确配置环境变量 `TENCENTCLOUD_SECRET_ID` 或 `TENCENTCLOUD_SECRET_KEY`

**解决方案**:
1. 确认 `.env` 文件已创建并包含正确的密钥
2. 确认在启动服务前已加载环境变量
3. 检查环境变量名称是否正确（区分大小写）

### 错误: "VOD upload failed"

**可能原因**:
- 网络连接问题
- API密钥无效或已过期
- 文件格式不支持
- 文件大小超限

**解决方案**:
1. 检查网络连接
2. 验证API密钥是否有效
3. 确认文件格式符合要求
4. 查看详细错误信息进行排查

## 环境变量配置

| 变量名 | 必填 | 说明 |
|--------|------|------|
| TENCENTCLOUD_SECRET_ID | 是 | 腾讯云API密钥ID |
| TENCENTCLOUD_SECRET_KEY | 是 | 腾讯云API密钥Key |

## 许可证

请遵守腾讯云服务协议和相关法律法规使用本服务。

## 支持

如有问题，请联系技术支持或提交Issue。

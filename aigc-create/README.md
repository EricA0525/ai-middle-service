# 腾讯云AIGC视频生成服务 API

本服务提供了基于腾讯云VOD的AIGC视频生成功能，包括任务创建和状态查询接口。

## 功能特性

- 创建AIGC视频生成任务
- 查询任务执行状态和结果
- 支持多种AI模型（Hailuo、Kling、Vidu等）
- 支持文生视频和图生视频
- 自动化的TC3签名认证

## 环境要求

- Python 3.7+
- FastAPI
- 腾讯云Python SDK

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn tencentcloud-sdk-python
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
- ReDoc: http://localhost:8000/redoc

## API接口说明

### 1. 创建AIGC视频任务

**接口**: `POST /aigc/create`

**请求示例**:
```json
{
  "prompt": "一个小男孩在街上跑步",
  "model_name": "Hailuo",
  "model_version": "2.3",
  "duration": 6,
  "resolution": "768P",
  "enhance_prompt": "Enabled"
}
```

**支持的模型**:
- **Hailuo** (海螺): 版本 "02", "2.3", "2.3-fast"
- **Kling** (可灵): 版本 "1.6", "2.0", "2.1", "2.5", "O1"
- **OS**: 默认模型

### 2. 查询任务状态

**接口**: `POST /aigc/task`

**请求示例**:
```json
{
  "task_id": "1234567890-task-id"
}
```

## 常见问题

### 错误: "Missing credentials"

**原因**: 未正确配置环境变量 `TENCENTCLOUD_SECRET_ID` 或 `TENCENTCLOUD_SECRET_KEY`

**解决方案**:
1. 确认 `.env` 文件已创建并包含正确的密钥
2. 确认在启动服务前已加载环境变量
3. 检查环境变量名称是否正确（区分大小写）

### 错误: "API请求失败"

**可能原因**:
- 网络连接问题
- API密钥无效或已过期
- 子应用ID配置错误
- API参数格式错误

**解决方案**:
1. 检查网络连接
2. 验证API密钥是否有效
3. 确认子应用ID (SubAppId) 配置正确
4. 查看详细错误信息进行排查

## 配置说明

### 环境变量

| 变量名 | 必填 | 说明 |
|--------|------|------|
| TENCENTCLOUD_SECRET_ID | 是 | 腾讯云API密钥ID |
| TENCENTCLOUD_SECRET_KEY | 是 | 腾讯云API密钥Key |

### 子应用配置

当前配置的子应用ID为 `1320866336`，如需修改请在代码中搜索 `SubAppId` 进行调整。

## 许可证

请遵守腾讯云服务协议和相关法律法规使用本服务。

## 支持

如有问题，请联系技术支持或提交Issue。

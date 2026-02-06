# AI Middle Service

AI 中间服务集合，提供多个腾讯云相关的 API 服务。

## 项目结构

```
ai-middle-service/
├── aigc-create/          # 腾讯云 AIGC 视频生成服务
├── tc-api/               # 腾讯云 API 包装服务
└── market-insight/       # 市场洞察服务
```

## 快速开始

### 环境配置

所有服务都需要配置腾讯云密钥。你可以选择以下任一方式：

#### 方式 1：使用根目录 .env 文件（推荐）

1. 复制根目录的 `.env.example` 为 `.env`：
   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env` 文件，填写你的腾讯云密钥：
   ```bash
   TENCENTCLOUD_SECRET_ID=your_secret_id_here
   TENCENTCLOUD_SECRET_KEY=your_secret_key_here
   ```

3. 在启动服务前，导入环境变量：
   ```bash
   export $(cat .env | xargs)
   ```

#### 方式 2：为每个服务单独配置

在每个服务目录下创建各自的 `.env` 文件：

```bash
cd aigc-create && cp .env.example .env
cd ../tc-api && cp .env.example .env
```

### 获取腾讯云密钥

访问 [腾讯云控制台 - API 密钥管理](https://console.cloud.tencent.com/cam/capi) 获取你的 SecretId 和 SecretKey。

**重要提示：** 
- 密钥具有账号完整权限，请妥善保管
- 不要将 `.env` 文件提交到版本控制系统（已添加到 `.gitignore`）

## 服务说明

### 1. AIGC 视频生成服务 (aigc-create)

提供腾讯云 VOD AIGC 视频生成任务的创建和查询接口。

**功能：**
- 创建 AIGC 视频生成任务（支持海螺、可灵等多种模型）
- 查询任务状态和详情
- 支持文生视频和图生视频

**详细文档：** [aigc-create/README.md](./aigc-create/README.md)

**启动命令：**
```bash
cd aigc-create
pip install fastapi uvicorn pydantic tencentcloud-sdk-python
uvicorn app:app --reload --port 8000
```

### 2. 腾讯云 API 包装服务 (tc-api)

提供腾讯云 VOD 上传和通用 API 调用的包装接口。

**功能：**
- VOD 视频/封面上传
- 通用云 API 调用接口
- 健康检查接口

**详细文档：** [tc-api/README.md](./tc-api/README.md)

**启动命令：**
```bash
cd tc-api
pip install fastapi uvicorn pydantic vod-python-sdk tencentcloud-sdk-python
uvicorn app:app --reload --port 8001
```

## 常见问题

### 错误：Missing credentials

**错误信息：**
```json
{
  "detail": "Missing credentials"
}
```

**原因：** 未配置环境变量 `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY`。

**解决方法：**

1. **检查 .env 文件是否存在：**
   ```bash
   ls -la .env
   ```

2. **检查 .env 文件内容：**
   ```bash
   cat .env
   ```
   确保包含以下内容（替换为你的实际密钥）：
   ```
   TENCENTCLOUD_SECRET_ID=your_secret_id_here
   TENCENTCLOUD_SECRET_KEY=your_secret_key_here
   ```

3. **导入环境变量：**
   ```bash
   export $(cat .env | xargs)
   ```
   或者使用 `source` 命令：
   ```bash
   set -a && source .env && set +a
   ```

4. **验证环境变量：**
   ```bash
   echo $TENCENTCLOUD_SECRET_ID
   echo $TENCENTCLOUD_SECRET_KEY
   ```
   应该能看到你配置的密钥值（非空）。

5. **重启服务：**
   ```bash
   # 停止当前运行的服务 (Ctrl+C)
   # 重新启动服务
   uvicorn app:app --reload
   ```

### 使用 Python 的 python-dotenv 自动加载

如果你希望服务自动加载 `.env` 文件，可以安装 `python-dotenv`：

```bash
pip install python-dotenv
```

然后在每个服务的 `app.py` 开头添加：

```python
from dotenv import load_dotenv
load_dotenv()  # 自动加载 .env 文件
```

## 部署建议

### Docker 部署

在 Docker 环境中，可以通过环境变量传递密钥：

```bash
docker run -e TENCENTCLOUD_SECRET_ID=xxx -e TENCENTCLOUD_SECRET_KEY=yyy ...
```

或使用 docker-compose.yml：

```yaml
services:
  aigc-create:
    environment:
      - TENCENTCLOUD_SECRET_ID=${TENCENTCLOUD_SECRET_ID}
      - TENCENTCLOUD_SECRET_KEY=${TENCENTCLOUD_SECRET_KEY}
```

### 生产环境

建议使用云平台的密钥管理服务（如腾讯云 SSM）而非环境变量存储敏感信息。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

请参考各子项目的许可证信息。

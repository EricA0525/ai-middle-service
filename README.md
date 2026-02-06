# AI Middle Service

AI中间层服务集合，提供多个基于腾讯云的AI和视频处理服务。

## 项目结构

```
ai-middle-service/
├── aigc-create/          # AIGC视频生成服务
├── tc-api/              # 腾讯云API包装服务
└── market-insight/      # 市场洞察服务
```

## 服务说明

### 1. AIGC视频生成服务 (aigc-create)

提供基于腾讯云VOD的AIGC视频生成功能。

**功能特性**：
- 创建AIGC视频生成任务
- 查询任务执行状态
- 支持多种AI模型（Hailuo、Kling等）
- 支持文生视频和图生视频

**详细文档**: [aigc-create/README.md](./aigc-create/README.md)

### 2. 腾讯云API包装服务 (tc-api)

提供腾讯云API的包装接口。

**功能特性**：
- VOD视频服务端上传
- 通用腾讯云API调用
- 支持多地域配置

**详细文档**: [tc-api/README.md](./tc-api/README.md)

### 3. 市场洞察服务 (market-insight)

提供健康品牌TikTok洞察分析功能。

**详细文档**: [market-insight/health_tk_insight-master/backend/README.md](./market-insight/health_tk_insight-master/backend/README.md)

## 快速开始

### 前置要求

所有服务都需要配置腾讯云API密钥，请先准备以下信息：

- 腾讯云 Secret ID
- 腾讯云 Secret Key

**获取腾讯云API密钥**：

1. 登录 [腾讯云控制台](https://console.cloud.tencent.com/)
2. 点击右上角账号 -> 访问管理
3. 左侧菜单选择 "访问密钥" -> "API密钥管理"
4. 创建或查看现有密钥

### 环境配置

每个服务都需要配置环境变量。以 aigc-create 服务为例：

```bash
# 进入服务目录
cd aigc-create

# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入您的腾讯云密钥
# TENCENTCLOUD_SECRET_ID=your_actual_secret_id
# TENCENTCLOUD_SECRET_KEY=your_actual_secret_key
```

### 启动服务

每个服务的启动方式请参考对应服务目录下的 README.md 文件。

一般启动命令：

```bash
# 安装依赖
pip install -r requirements.txt  # 如果有 requirements.txt
# 或
pip install fastapi uvicorn tencentcloud-sdk-python

# 启动服务
export $(cat .env | xargs) && uvicorn app:app --host 0.0.0.0 --port 8000
```

## 常见问题

### 错误: "Missing credentials"

**原因**: 未正确配置环境变量

**解决方案**:
1. 确认在对应服务目录下创建了 `.env` 文件
2. 确认 `.env` 文件包含正确的 `TENCENTCLOUD_SECRET_ID` 和 `TENCENTCLOUD_SECRET_KEY`
3. 确认在启动服务前已加载环境变量

### 多服务端口配置

如果需要同时运行多个服务，请为每个服务配置不同的端口：

```bash
# aigc-create 服务 - 端口 8001
cd aigc-create
export $(cat .env | xargs) && uvicorn app:app --host 0.0.0.0 --port 8001

# tc-api 服务 - 端口 8002
cd tc-api
export $(cat .env | xargs) && uvicorn app:app --host 0.0.0.0 --port 8002
```

## 安全注意事项

⚠️ **重要提示**：

1. **不要将 `.env` 文件提交到版本控制系统**
   - `.env` 文件已添加到 `.gitignore`
   - 仅提交 `.env.example` 作为模板

2. **不要在代码中硬编码密钥**
   - 始终使用环境变量
   - 使用配置管理工具（如 vault）存储敏感信息

3. **定期更换API密钥**
   - 建议定期更新密钥
   - 发现泄露立即更换

4. **限制密钥权限范围**
   - 使用最小权限原则
   - 仅授予必要的API权限

## 开发指南

### 添加新服务

1. 在项目根目录创建新的服务目录
2. 创建 `.env.example` 文件说明所需环境变量
3. 创建 `README.md` 文档服务功能和使用方法
4. 更新本文档添加新服务说明

### 环境变量命名规范

- 使用大写字母和下划线
- 前缀表示服务类型（如 `TENCENTCLOUD_`）
- 清晰描述变量用途

## 贡献

欢迎提交Issue和Pull Request改进本项目。

## 许可证

请遵守腾讯云服务协议和相关法律法规使用本服务。

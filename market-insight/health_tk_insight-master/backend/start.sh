#!/bin/bash
# ===========================================
# Market Insight Agent - Startup Script
# ===========================================
# 启动脚本，用于在8100端口启动服务

set -e

echo "=========================================="
echo "Market Insight Agent - Starting Service"
echo "=========================================="

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查.env文件是否存在
if [ ! -f .env ]; then
    echo "⚠️  .env file not found, copying from .env.8100..."
    if [ -f .env.8100 ]; then
        cp .env.8100 .env
        echo "✅ .env file created from .env.8100 (configured for port 8100)."
    elif [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ .env file created from .env.example."
        echo "⚠️  Please edit .env to set API_PORT=8100"
    else
        echo "❌ No template file found (.env.8100 or .env.example)"
        exit 1
    fi
    echo "📝 Please edit .env to add your API keys if needed."
fi

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3."
    exit 1
fi

# 检查依赖是否安装
if ! python3 -c "import fastapi" &> /dev/null; then
    echo "⚠️  Dependencies not installed. Installing..."
    pip install -r requirements.txt
fi

# 读取端口配置 (从.env文件或环境变量，默认8100)
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep API_PORT | xargs)
fi
PORT=${API_PORT:-8100}

echo ""
echo "🚀 Starting service on port $PORT..."
echo "📝 API Documentation: http://localhost:$PORT/docs"
echo "🔍 Health Check: http://localhost:$PORT/health"
echo ""

# 启动服务
uvicorn app.main:app --host 0.0.0.0 --port $PORT --reload

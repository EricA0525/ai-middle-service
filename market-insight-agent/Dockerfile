FROM python:3.11-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# 安装必要的系统库（针对 lxml 和其他编译依赖）
RUN apt-get update && apt-get install -y \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
# 注意：在构建时可以通过 .dockerignore 排除 venv 等
COPY . .

# 确保输出目录存在
RUN mkdir -p output

# 暴露内部端口
EXPOSE 8000

# 运行 FastAPI 应用
CMD ["uvicorn", "market_insight_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

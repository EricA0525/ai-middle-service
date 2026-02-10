@echo off
REM ===========================================
REM Market Insight Agent - Startup Script (Windows)
REM ===========================================
REM 启动脚本，用于在8100端口启动服务

echo ==========================================
echo Market Insight Agent - Starting Service
echo ==========================================
echo.

REM 切换到脚本所在目录
cd /d %~dp0

REM 检查.env文件是否存在
if not exist .env (
    echo [WARNING] .env file not found, copying from .env.example...
    copy .env.example .env
    echo [SUCCESS] .env file created. Please edit it to add your API keys.
)

REM 检查Python环境
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed. Please install Python 3.
    pause
    exit /b 1
)

REM 检查依赖是否安装
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Dependencies not installed. Installing...
    pip install -r requirements.txt
)

REM 读取端口配置（默认8100）
set PORT=8100
if defined API_PORT set PORT=%API_PORT%

echo.
echo [INFO] Starting service on port %PORT%...
echo.

REM 启动服务
uvicorn app.main:app --host 0.0.0.0 --port %PORT% --reload

echo.
echo [SUCCESS] Service started successfully!
echo [INFO] API Documentation: http://localhost:%PORT%/docs
echo [INFO] Health Check: http://localhost:%PORT%/health
echo.
pause

"""
API 请求日志中间件
==================
记录所有 API 请求和响应的详细信息，包括：
- 请求信息：方法、路径、参数、客户端IP
- 响应信息：状态码、响应时间、响应大小
- 错误信息：异常堆栈
"""

import json
import time
from typing import Callable

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    记录所有 HTTP 请求和响应的中间件
    
    功能：
    1. 记录请求详情（方法、路径、查询参数、请求体）
    2. 记录响应详情（状态码、响应时间、响应体大小）
    3. 记录异常和错误
    4. 自动计算请求处理时长
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        处理每个 HTTP 请求
        
        Args:
            request: FastAPI 请求对象
            call_next: 下一个中间件或路由处理函数
            
        Returns:
            Response: HTTP 响应对象
        """
        # 记录请求开始时间
        start_time = time.time()
        
        # 提取请求信息
        request_info = {
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", "unknown"),
        }
        
        # 尝试读取请求体（仅对 POST/PUT/PATCH 请求）
        request_body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                # 读取请求体
                body = await request.body()
                if body:
                    # 尝试解析为 JSON
                    try:
                        request_body = json.loads(body.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        request_body = f"<binary data, {len(body)} bytes>"
                    
                    # 重建请求以便后续处理器可以读取
                    async def receive() -> Message:
                        return {"type": "http.request", "body": body}
                    
                    request._receive = receive
            except Exception as e:
                logger.warning(f"Failed to read request body: {e}")
        
        # 记录请求开始
        logger.info(
            f"API Request Started | {request_info['method']} {request_info['path']} | "
            f"Client: {request_info['client_ip']}"
        )
        
        # 处理请求并捕获异常
        response = None
        error = None
        try:
            response = await call_next(request)
        except Exception as exc:
            error = exc
            logger.exception(f"API Request Failed | {request_info['method']} {request_info['path']}")
            raise
        finally:
            # 计算请求处理时长
            process_time = time.time() - start_time
            
            # 准备日志信息
            log_data = {
                **request_info,
                "process_time_ms": round(process_time * 1000, 2),
            }
            
            if request_body is not None:
                # 对于敏感数据，可以在这里进行脱敏处理
                log_data["request_body"] = request_body
            
            if response:
                log_data["status_code"] = response.status_code
                log_data["success"] = 200 <= response.status_code < 400
                
                # 记录成功或失败的请求
                if log_data["success"]:
                    logger.info(
                        f"API Request Success | {request_info['method']} {request_info['path']} | "
                        f"Status: {response.status_code} | "
                        f"Time: {log_data['process_time_ms']}ms"
                    )
                else:
                    logger.warning(
                        f"API Request Failed | {request_info['method']} {request_info['path']} | "
                        f"Status: {response.status_code} | "
                        f"Time: {log_data['process_time_ms']}ms"
                    )
                
                # 在详细日志级别记录完整信息
                logger.debug(f"Request Details: {json.dumps(log_data, ensure_ascii=False)}")
            
            elif error:
                log_data["error"] = str(error)
                log_data["success"] = False
                logger.error(
                    f"API Request Error | {request_info['method']} {request_info['path']} | "
                    f"Error: {str(error)} | "
                    f"Time: {log_data['process_time_ms']}ms"
                )
        
        return response

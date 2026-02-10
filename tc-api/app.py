import os
import tempfile
from typing import Any, Dict, Optional, Callable
import json
import time

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Message

from qcloud_vod.vod_upload_client import VodUploadClient
from qcloud_vod.model import VodUploadRequest

from tencentcloud.common import credential
from tencentcloud.common.common_client import CommonClient
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException


class APILoggingMiddleware(BaseHTTPMiddleware):
    """
    API 请求日志中间件
    记录所有 API 请求和响应的详细信息
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """处理每个 HTTP 请求并记录日志"""
        start_time = time.time()
        
        # 提取请求信息
        request_info = {
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_ip": request.client.host if request.client else "unknown",
        }
        
        # 读取请求体
        request_body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    try:
                        request_body = json.loads(body.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        request_body = f"<binary data, {len(body)} bytes>"
                    
                    # 重建请求以便后续处理器可以读取
                    async def receive() -> Message:
                        return {"type": "http.request", "body": body}
                    
                    request._receive = receive
            except Exception as e:
                print(f"[WARNING] Failed to read request body: {e}")
        
        # 记录请求开始
        print(f"[INFO] API Request Started | {request_info['method']} {request_info['path']} | Client: {request_info['client_ip']}")
        
        # 处理请求并捕获异常
        response = None
        error = None
        try:
            response = await call_next(request)
        except Exception as exc:
            error = exc
            print(f"[ERROR] API Request Exception | {request_info['method']} {request_info['path']} | Error: {str(exc)}")
            raise
        finally:
            # 计算请求处理时长
            process_time = time.time() - start_time
            process_time_ms = round(process_time * 1000, 2)
            
            # 准备日志信息
            log_data = {
                **request_info,
                "process_time_ms": process_time_ms,
            }
            
            if request_body is not None:
                log_data["request_body"] = request_body
            
            if response:
                log_data["status_code"] = response.status_code
                log_data["success"] = 200 <= response.status_code < 400
                
                # 记录成功或失败的请求
                if log_data["success"]:
                    print(
                        f"[INFO] API Request Success | {request_info['method']} {request_info['path']} | "
                        f"Status: {response.status_code} | Time: {process_time_ms}ms"
                    )
                else:
                    print(
                        f"[WARNING] API Request Failed | {request_info['method']} {request_info['path']} | "
                        f"Status: {response.status_code} | Time: {process_time_ms}ms"
                    )
                
                # 详细日志
                print(f"[DEBUG] Request Details: {json.dumps(log_data, ensure_ascii=False)}")
            
            elif error:
                log_data["error"] = str(error)
                log_data["success"] = False
                print(
                    f"[ERROR] API Request Error | {request_info['method']} {request_info['path']} | "
                    f"Error: {str(error)} | Time: {process_time_ms}ms"
                )
        
        return response


app = FastAPI(title="TencentCloud API Wrapper")

# 注册日志中间件
app.add_middleware(APILoggingMiddleware)

def get_cred():
    sid = os.getenv("TENCENTCLOUD_SECRET_ID")
    sk = os.getenv("TENCENTCLOUD_SECRET_KEY")
    if not sid or not sk:
        raise HTTPException(500, "Missing TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY")
    return credential.Credential(sid, sk)

@app.get("/health")
def health():
    return {"ok": True}

# 1) VOD 服务端上传（给 Apifox 直接上传文件）
@app.post("/vod/upload")
async def vod_upload(
    region: str = Form("ap-guangzhou"),
    procedure: Optional[str] = Form(None),
    sub_app_id: Optional[int] = Form(None),
    media: UploadFile = File(...),
    cover: Optional[UploadFile] = File(None),
):
    with tempfile.TemporaryDirectory() as td:
        media_path = os.path.join(td, media.filename)
        with open(media_path, "wb") as f:
            f.write(await media.read())

        cover_path = None
        if cover is not None:
            cover_path = os.path.join(td, cover.filename)
            with open(cover_path, "wb") as f:
                f.write(await cover.read())

        client = VodUploadClient(os.environ["TENCENTCLOUD_SECRET_ID"], os.environ["TENCENTCLOUD_SECRET_KEY"])
        req = VodUploadRequest()
        req.MediaFilePath = media_path
        if cover_path:
            req.CoverFilePath = cover_path
        if procedure:
            req.Procedure = procedure
        if sub_app_id:
            req.SubAppId = sub_app_id

        try:
            resp = client.upload(region, req)
            return {
                "fileId": getattr(resp, "FileId", None),
                "mediaUrl": getattr(resp, "MediaUrl", None),
                "coverUrl": getattr(resp, "CoverUrl", None),
            }
        except Exception as e:
            raise HTTPException(500, f"VOD upload failed: {e}")

# 2) 通用云 API 调用（Apifox 传 action/version/params 即可）
class TcCallIn(BaseModel):
    service: str
    version: str
    action: str
    region: str
    params: Dict[str, Any] = {}

@app.post("/tencentcloud/call")
def tencentcloud_call(body: TcCallIn):
    cred = get_cred()
    client = CommonClient(body.service, body.version, cred, body.region, profile=None)
    try:
        resp_json = client.call_json(body.action, body.params)
        return {"response": resp_json}
    except TencentCloudSDKException as e:
        raise HTTPException(400, f"TencentCloudSDKException: {e}")
    except Exception as e:
        raise HTTPException(500, f"Call failed: {e}")

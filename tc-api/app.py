import os
import tempfile
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from pydantic import BaseModel

from qcloud_vod.vod_upload_client import VodUploadClient
from qcloud_vod.model import VodUploadRequest

from tencentcloud.common import credential
from tencentcloud.common.common_client import CommonClient
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException

app = FastAPI(title="TencentCloud API Wrapper")

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

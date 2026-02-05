# -*- coding: utf-8 -*-
import os
import hashlib
import hmac
import json
import time
from datetime import datetime
from http.client import HTTPSConnection
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.vod.v20180717 import vod_client, models

app = FastAPI()

def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

# ============ 创建任务接口 ============
class AigcRequest(BaseModel):
    prompt: str
    file_id: Optional[str] = None
    model_name: Optional[str] = "OS"
    model_version: Optional[str] = "2.0"
    duration: Optional[float] = None

@app.post("/aigc/create")
def create_aigc_task(req: AigcRequest):
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    
    if not secret_id or not secret_key:
        raise HTTPException(status_code=500, detail="Missing credentials")
    
    service = "vod"
    host = "vod.tencentcloudapi.com"
    version = "2018-07-17"
    action = "CreateAigcVideoTask"

    # build payload using incoming parameters (model name/version and optional duration)
    payload_data = {
        "SubAppId": 1320866336,
        "ModelName": req.model_name,
        "ModelVersion": req.model_version,
        "Prompt": req.prompt
    }

    if req.file_id:
        payload_data["FileInfos"] = [
            {
                "ReferenceType": "File",
                "FileId": req.file_id
            }
        ]

    # include OutputConfig.Duration when provided
    if req.duration is not None:
        # coerce to a numeric type (float) to avoid sending a string
        try:
            duration_value = float(req.duration)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid duration value")
        payload_data["OutputConfig"] = {"Duration": duration_value}

    # debug: print final payload so we can inspect exact JSON sent to Tencent
    payload = json.dumps(payload_data)
    print("[DEBUG] CreateAigcVideoTask payload:", payload)
    
    algorithm = "TC3-HMAC-SHA256"
    timestamp = int(time.time())
    date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    
    ct = "application/json; charset=utf-8"
    canonical_headers = "content-type:%s\nhost:%s\nx-tc-action:%s\n" % (ct, host, action.lower())
    signed_headers = "content-type;host;x-tc-action"
    hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = ("POST\n/\n\n" + canonical_headers + "\n" + signed_headers + "\n" + hashed_request_payload)
    
    credential_scope = date + "/" + service + "/tc3_request"
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = algorithm + "\n" + str(timestamp) + "\n" + credential_scope + "\n" + hashed_canonical_request
    
    secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = sign(secret_date, service)
    secret_signing = sign(secret_service, "tc3_request")
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    
    authorization = (algorithm + " Credential=" + secret_id + "/" + credential_scope + 
                    ", SignedHeaders=" + signed_headers + ", Signature=" + signature)
    
    headers = {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": version
    }
    
    try:
        conn = HTTPSConnection(host)
        conn.request("POST", "/", headers=headers, body=payload.encode("utf-8"))
        resp = conn.getresponse()
        result = json.loads(resp.read().decode("utf-8"))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============ 查询任务接口 ============
class TaskDetailRequest(BaseModel):
    task_id: str

@app.post("/aigc/task")
def get_task_detail(req: TaskDetailRequest):
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    
    if not secret_id or not secret_key:
        raise HTTPException(status_code=500, detail="Missing credentials")
    
    try:
        cred = credential.Credential(secret_id, secret_key)
        
        httpProfile = HttpProfile()
        httpProfile.endpoint = "vod.tencentcloudapi.com"
        
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        
        client = vod_client.VodClient(cred, "", clientProfile)
        
        request = models.DescribeTaskDetailRequest()
        params = {
            "TaskId": req.task_id,
            "SubAppId": 1320866336
        }
        request.from_json_string(json.dumps(params))
        
        resp = client.DescribeTaskDetail(request)
        return json.loads(resp.to_json_string())
    
    except TencentCloudSDKException as err:
        raise HTTPException(status_code=500, detail=str(err))
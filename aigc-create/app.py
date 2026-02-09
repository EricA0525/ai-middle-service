# -*- coding: utf-8 -*-
"""
腾讯云VOD AIGC视频生成服务 API
本模块提供了创建AIGC视频任务和查询任务状态的FastAPI接口
"""

import os
import hashlib
import hmac
import json
import time
from datetime import datetime
from http.client import HTTPSConnection
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# 腾讯云SDK相关导入
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.vod.v20180717 import vod_client, models

# 创建FastAPI应用实例
app = FastAPI(
    title="腾讯云AIGC视频生成服务",
    description="提供AIGC视频生成任务创建和状态查询接口",
    version="1.0.0",
    docs_url="/docs",      # Swagger UI
    redoc_url="/redoc",    # ReDoc UI
)


def sign(key: bytes, msg: str) -> bytes:
    """
    使用HMAC-SHA256算法进行签名
    
    Args:
        key: 签名密钥（字节类型）
        msg: 需要签名的消息（字符串类型）
    
    Returns:
        签名后的字节数据
    """
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


# ============ 创建任务接口 ============

class AigcRequest(BaseModel):
    """
    AIGC视频生成任务请求模型
    
    Attributes:
        prompt: 视频生成的提示词（必填）
        file_id: 参考文件ID，用于图生视频等场景（可选）
        model_name: 模型名称（可选）
            - "Hailuo": 海螺模型
            - "Kling": 可灵模型
            - "OS": 默认模型
        model_version: 模型版本（可选）
            - Hailuo: "02", "2.3", "2.3-fast"
            - Kling: "1.6", "2.0", "2.1", "2.5", "O1"
        duration: 输出视频时长（可选）
            - Hailuo: 6, 10（默认6）
            - Kling: 5, 10（默认5）
        resolution: 视频分辨率（可选）
            - Hailuo: "768P", "1080P"（默认768P）
            - Kling: "720P", "1080P"（默认720P）
        aspect_ratio: 宽高比，仅Kling文生视频支持（可选）
            - "16:9", "9:16", "1:1"（默认16:9）
        enhance_switch: 是否开启超分增强（可选）
            - "Enabled": 开启
            - "Disabled": 关闭
        enhance_prompt: 是否增强提示词（可选）
            - "Enabled": 开启
            - "Disabled": 关闭
        frame_interpolate: 智能插帧，仅Vidu支持（可选）
            - "Enabled": 开启
            - "Disabled": 关闭
        tasks_priority: 任务优先级，-10到10，数值越大优先级越高（可选，默认0）
        scene_type: 场景类型，仅Kling支持（可选）
    """
    prompt: str = "一个小男孩在街上跑步"
    file_id: Optional[str] = Field(default=None, examples=[None])
    model_name: Optional[str] = "Hailuo"
    model_version: Optional[str] = "2.3"
    duration: Optional[int] = 6
    resolution: Optional[str] = "768P"
    aspect_ratio: Optional[str] = "16:9"
    audio_generation: str = "Enabled"
    enhance_switch: Optional[str] = "Disabled"
    enhance_prompt: Optional[str] = "Enabled"
    frame_interpolate: Optional[str] = "Disabled"
    tasks_priority: Optional[int] = 10
    scene_type: Optional[str] = Field(default=None, examples=[None])


@app.post("/aigc/create")
def create_aigc_task(req: AigcRequest):
    """
    创建AIGC视频生成任务
    
    该接口使用腾讯云TC3签名方式手动构建请求，调用VOD的CreateAigcVideoTask接口
    
    Args:
        req: AIGC任务请求参数
    
    Returns:
        腾讯云API返回的JSON响应，包含任务ID等信息
    
    Raises:
        HTTPException: 当凭证缺失或API调用失败时抛出
    """
    # 从环境变量获取腾讯云密钥
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    
    # 检查密钥是否存在
    if not secret_id or not secret_key:
        raise HTTPException(status_code=500, detail="Missing credentials")
    
    # 腾讯云API基础配置
    service = "vod"                           # 服务名称
    host = "vod.tencentcloudapi.com"          # API域名
    version = "2018-07-17"                    # API版本
    action = "CreateAigcVideoTask"            # API操作名称

    # 构建请求体数据
    payload_data = {
        "SubAppId": 1320866336,                # VOD子应用ID
        "ModelName": req.model_name,           # 模型名称
        "ModelVersion": req.model_version,     # 模型版本
        "Prompt": req.prompt                   # 生成提示词
    }

    # 如果提供了文件ID，添加文件信息（用于图生视频等场景）
    if req.file_id:
        payload_data["FileInfos"] = [
            {
                "ReferenceType": "File",       # 引用类型为文件
                "FileId": req.file_id          # 文件ID
            }
        ]

    # 是否增强提示词
    if req.enhance_prompt:
        payload_data["EnhancePrompt"] = req.enhance_prompt

    # 构建 OutputConfig 输出配置
    output_config = {}
    
    # 视频时长
    if req.duration is not None:
        output_config["Duration"] = req.duration
    
    # 视频分辨率
    if req.resolution:
        output_config["Resolution"] = req.resolution
    
    # 宽高比（仅Kling文生视频支持）
    if req.aspect_ratio:
        output_config["AspectRatio"] = req.aspect_ratio
    
    # 超分增强开关
    if req.enhance_switch:
        output_config["EnhanceSwitch"] = req.enhance_switch
    
    # 智能插帧（仅Vidu支持）
    if req.frame_interpolate:
        output_config["FrameInterpolate"] = req.frame_interpolate

    # 音频生成开关（使用请求参数）
    if req.audio_generation:  # ✅ 修复：使用 req.audio_generation
        output_config["AudioGeneration"] = req.audio_generation  # ✅ 修复：正确拼写
    
    # 人物生成配置
    output_config["PersonGeneration"] = "AllowAdult"
    
    # 如果有输出配置，添加到请求体
    if output_config:
        payload_data["OutputConfig"] = output_config

    # 任务优先级（-10到10）
    if req.tasks_priority is not None:
        payload_data["TasksPriority"] = req.tasks_priority

    # 场景类型（仅Kling支持）
    if req.scene_type:
        payload_data["SceneType"] = req.scene_type

    # 调试：打印最终发送给腾讯云的请求体
    payload = json.dumps(payload_data)
    print("[DEBUG] CreateAigcVideoTask payload:", payload)
    
    # ========== TC3签名计算开始 ==========
    # 签名算法和时间戳
    algorithm = "TC3-HMAC-SHA256"              # 使用TC3-HMAC-SHA256签名算法
    timestamp = int(time.time())               # 当前Unix时间戳
    date = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")  # UTC日期
    
    # 构建规范请求串
    ct = "application/json; charset=utf-8"     # Content-Type
    # 规范头部：必须按字母顺序排列，且使用小写
    canonical_headers = "content-type:%s\nhost:%s\nx-tc-action:%s\n" % (ct, host, action.lower())
    signed_headers = "content-type;host;x-tc-action"  # 参与签名的头部列表
    # 计算请求体的SHA256哈希值
    hashed_request_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    # 组装规范请求串
    canonical_request = ("POST\n/\n\n" + canonical_headers + "\n" + signed_headers + "\n" + hashed_request_payload)
    
    # 构建待签名字符串
    credential_scope = date + "/" + service + "/tc3_request"  # 凭证范围
    hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = algorithm + "\n" + str(timestamp) + "\n" + credential_scope + "\n" + hashed_canonical_request
    
    # 计算签名：使用派生密钥进行多层HMAC签名
    secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)      # 第一层：日期
    secret_service = sign(secret_date, service)                          # 第二层：服务
    secret_signing = sign(secret_service, "tc3_request")                 # 第三层：请求类型
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    
    # 组装Authorization头部
    authorization = (algorithm + " Credential=" + secret_id + "/" + credential_scope + 
                    ", SignedHeaders=" + signed_headers + ", Signature=" + signature)
    # ========== TC3签名计算结束 ==========
    
    # 构建HTTP请求头
    headers = {
        "Authorization": authorization,        # 签名授权信息
        "Content-Type": ct,                    # 内容类型
        "Host": host,                          # 主机名
        "X-TC-Action": action,                 # API操作名
        "X-TC-Timestamp": str(timestamp),      # 时间戳
        "X-TC-Version": version                # API版本
    }
    
    # 发送HTTPS请求
    try:
        conn = HTTPSConnection(host, timeout=1800)  # 创建HTTPS连接，超时30分钟
        conn.request("POST", "/", headers=headers, body=payload.encode("utf-8"))
        resp = conn.getresponse()              # 获取响应
        result = json.loads(resp.read().decode("utf-8"))  # 解析JSON响应
        return result
    except TimeoutError:
        raise HTTPException(status_code=504, detail="请求腾讯云API超时，请稍后重试")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"API请求失败: {str(e)}")


# ============ 查询任务接口 ============

class TaskDetailRequest(BaseModel):
    """
    任务详情查询请求模型
    
    Attributes:
        task_id: 任务ID，由创建任务接口返回
    """
    task_id: str


@app.post("/aigc/task")
def get_task_detail(req: TaskDetailRequest):
    """
    查询AIGC视频任务详情
    
    该接口使用腾讯云Python SDK调用VOD的DescribeTaskDetail接口，
    用于查询任务的执行状态和结果
    
    Args:
        req: 包含任务ID的请求参数
    
    Returns:
        任务详情的JSON响应，包含任务状态、进度、输出文件等信息
    
    Raises:
        HTTPException: 当凭证缺失或API调用失败时抛出
    """
    # 从环境变量获取腾讯云密钥
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID")
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY")
    
    # 检查密钥是否存在
    if not secret_id or not secret_key:
        raise HTTPException(status_code=500, detail="Missing credentials")
    
    try:
        # 创建腾讯云认证对象
        cred = credential.Credential(secret_id, secret_key)
        
        # 配置HTTP访问参数
        httpProfile = HttpProfile()
        httpProfile.endpoint = "vod.tencentcloudapi.com"  # API访问域名
        
        # 配置客户端参数
        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile
        
        # 创建VOD客户端实例（第二个参数为空表示不指定地域）
        client = vod_client.VodClient(cred, "", clientProfile)
        
        # 构建请求对象
        request = models.DescribeTaskDetailRequest()
        params = {
            "TaskId": req.task_id,             # 要查询的任务ID
            "SubAppId": 1320866336             # VOD子应用ID
        }
        request.from_json_string(json.dumps(params))  # 将参数转换为请求对象
        
        # 发起API调用并返回结果
        resp = client.DescribeTaskDetail(request)
        return json.loads(resp.to_json_string())
    
    except TencentCloudSDKException as err:
        # 捕获腾讯云SDK异常并返回错误信息
        raise HTTPException(status_code=500, detail=str(err))

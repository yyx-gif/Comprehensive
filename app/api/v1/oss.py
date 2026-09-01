import alibabacloud_oss_v2 as oss
from fastapi import APIRouter
from datetime import timedelta
import os
# 加载环境变量
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

# 从环境变量中加载凭证信息，用于身份验证
credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()

# 加载SDK的默认配置，并设置凭证提供者
cfg = oss.config.load_default()
cfg.credentials_provider = credentials_provider

# 方式一：只填写Region（推荐）
# 必须指定Region ID，SDK会根据Region自动构造HTTPS访问域名
cfg.region = 'cn-beijing'

# 使用配置好的信息创建OSS客户端
client = oss.Client(cfg)

# OSS 域名配置
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")
OSS_BUCKET = os.getenv("OSS_BUCKET")


@router.get("/oss/presign")
def chat_endpoint(filename: str):
    # 根据文件扩展名判断 Content-Type
    content_type_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
    }
    ext = filename.split(".")[-1].lower() if "." in filename else "jpg"
    content_type = content_type_map.get(ext, "application/octet-stream")

    upload_pre = client.presign(oss.PutObjectRequest(
        bucket=OSS_BUCKET,
        key=filename,
        content_type=content_type,
    ), expires=timedelta(seconds=3600))

    # 关键修复：生成 GET 签名的临时访问 URL，确保模型侧（DashScope/阿里云内网）能匿名拉取到图片
    # 如果 bucket 是公网可读，裸 URL 也行；私有时必须对 GET 做 presign，有效期 2 小时
    get_pre = client.presign(oss.GetObjectRequest(
        bucket=OSS_BUCKET,
        key=filename,
    ), expires=timedelta(seconds=7200))
    access_url = get_pre.url.strip('"')

    return {
        "uploadUrl": upload_pre.url.strip('"'),
        "contentType": content_type,
        "accessUrl": access_url,
    }

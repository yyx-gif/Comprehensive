import os
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import chat
from app.api.v1 import oss
from app.api.v1 import sessions
from app.api.v1 import assistants
from app.common.logger import setup_logging
from contextlib import asynccontextmanager
from app.agents.email_agent import email_agent
# 初始化日志配置
setup_logging()

from dotenv import load_dotenv
load_dotenv()

# 使用 lifespan 管理 checkpointer 生命周期
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 启动时初始化 checkpointer 和 agent
    await email_agent.init()
    yield
    # 停机时，关闭连接
    await email_agent.close()

app = FastAPI(
    title="Personal Chief API",
    description="私厨",
    version="0.1.0",
    lifespan=lifespan
)

# 1. 配置跨域资源共享 (CORS)
# 插件开发中，由于请求来自浏览器扩展环境，必须正确配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议指定插件的 ID 或具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 禁用浏览器缓存，确保 CSS/JS/HTML 修改立即生效
@app.middleware("http")
async def disable_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# 2.挂载路由
app.include_router(chat.router, prefix="/api/v1", tags=["对话"])
app.include_router(oss.router, prefix="/api/v1", tags=["申请上传签名url"])
app.include_router(sessions.router, prefix="/api/v1", tags=["会话管理"])
app.include_router(assistants.router, prefix="/api/v1", tags=["助手对话"])

# 3.挂载前端资源
static_dir = os.path.join(os.path.dirname(__file__), "static")

# 综合智能助手门户首页（默认入口）
@app.get("/", include_in_schema=False)
async def portal_page():
    portal_path = os.path.join(static_dir, "portal.html")
    if os.path.exists(portal_path):
        return FileResponse(portal_path)
    return JSONResponse({"error": "portal.html not found"}, status_code=404)

# AI 私厨入口（注入主题覆盖 CSS/JS，不修改原始 index.html）
@app.get("/chief", include_in_schema=False)
async def chief_page():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        inject_links = (
            '<link rel="stylesheet" href="/chef-override.css?v=20260820p">'
            '<script src="/chef-override.js?v=20260820p"></script>'
        )
        if "</head>" in html:
            html = html.replace("</head>", inject_links + "</head>")
        # 移除 turbopack HMR 脚本（生产环境不需要，且会导致 SyntaxError）
        html = html.replace('<script src="/_next/static/chunks/turbopack-c23a98272a4b92c4.js" async=""></script>', '')
        response = HTMLResponse(html)
        response.headers["Clear-Site-Data"] = '"cache"'
        return response
    return JSONResponse({"error": "Not Found"}, status_code=404)

# AI 邮件助手入口（复用原 email.html，不修改其内容）
@app.get("/email", include_in_schema=False)
async def email_page():
    email_path = os.path.join(static_dir, "email.html")
    if os.path.exists(email_path):
        return FileResponse(email_path)
    return JSONResponse({"error": "Not Found"}, status_code=404)

# 新助手入口（6 个助手共用一个页面，通过 ?type= 区分）
@app.get("/assistant", include_in_schema=False)
async def assistant_page():
    assistant_path = os.path.join(static_dir, "assistant.html")
    if os.path.exists(assistant_path):
        return FileResponse(assistant_path)
    return JSONResponse({"error": "Not Found"}, status_code=404)

# 处理 @vite/client 请求 - 返回完整 shim，避免前端 SyntaxError
@app.get("/@vite/client", include_in_schema=False)
async def vite_client():
    shim = """export function createHotContext() { return { accept() {}, dispose() {}, invalidate() {}, on() {}, off() {}, send() {} } }
export function sendMessage() {}
export function connect() {}
export function injectScript() {}
export function defineAssetURL(url) { return url }
export default { createHotContext, sendMessage, connect, injectScript, defineAssetURL };"""
    return HTMLResponse(shim, media_type="text/javascript")

if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

# 前端 fallback 路由 - 只处理非 API 请求
@app.get("/{path:path}", include_in_schema=False)
async def serve_frontend(path: str):
    # 排除 API 路径
    if path.startswith("api/"):
        return JSONResponse({"error": "Not Found"}, status_code=404)
    # 如果请求的是静态文件，直接返回
    file_path = os.path.join(static_dir, path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    # 否则返回门户首页（SPA fallback）
    portal_path = os.path.join(static_dir, "portal.html")
    if os.path.exists(portal_path):
        return FileResponse(portal_path)
    return {"message": "综合智能助手", "status": "ok"}

if __name__ == "__main__":
    import uvicorn
    # 启动命令：python -m app.main
    # reload=True 时必须排除数据库文件（*.db / *.db-shm / *.db-wal），
    # 否则 SQLite 每次写入都会触发 uvicorn 重载，导致网页间歇性无法访问。
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8001,
        reload=True,
        reload_dirs=["app"],
        reload_excludes=["*.db", "*.db-*", "*.pyc", "__pycache__", "*.log"],
    )
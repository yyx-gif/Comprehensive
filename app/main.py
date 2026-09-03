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

# 只对 HTML/API 禁用缓存；静态资源（.css/.js/.woff2/.png 等）不干涉，
# 让 StaticFiles 默认的 Last-Modified / 304 机制生效，避免首屏反复拉资源时 DevTools 闪 404。
# 以前"所有响应都 no-store"会导致 CSS/JS/字体每次重请求+清缓存，
# 一旦 lifespan/重载卡住，就会出现"样式一闪错乱"的感知。
@app.middleware("http")
async def disable_cache(request, call_next):
    response = await call_next(request)
    path = request.url.path
    # 静态资源后缀 → 不改任何头，交给 StaticFiles/FileResponse 默认缓存策略
    _static_exts = (
        ".css", ".js", ".mjs", ".json",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".map",
    )
    if any(path.endswith(ext) for ext in _static_exts):
        return response
    # HTML / API 动态内容 → 禁用缓存，保证数据实时
    try:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    except Exception:
        pass
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
            '<link rel="stylesheet" href="/chef-override.css?v=20260902">'
            '<script src="/chef-override.js?v=20260902"></script>'
        )
        if "</head>" in html:
            html = html.replace("</head>", inject_links + "</head>")

        # —— 移除 Next.js 开发阶段遗留的 HMR/构建 manifest 脚本 ——
        # 这些文件即使存在，FastAPI + StaticFiles 也不会生成它们，
        # 会导致首屏 DevTools 连续 404，页面左上角闪过"拒绝链接"红错
        html = html.replace('<script src="/_next/static/chunks/turbopack-c23a98272a4b92c4.js" async=""></script>', '')
        html = html.replace('<script src="/_next/static/chunks/a6dad97d9634a72d.js" noModule=""></script>', '')

        # —— 修 favicon 路径：Next.js 产物里 favicon 写成了 /favicon.ico?xxx，但实际文件在 _next/static/media/ 下 ——
        html = html.replace('/favicon.ico?favicon.0b3bf435.ico', '/_next/static/media/favicon.0b3bf435.ico')
        # 去掉字符串内 self.__next_f 里 HL 对 favicon 的路径引用（同样的路径错误会 404）
        html = html.replace('"href":"/favicon.ico?favicon.0b3bf435.ico"', '"href":"/_next/static/media/favicon.0b3bf435.ico"')

        # —— 不再加 Content-Security-Policy ——
        # 上一版加的 CSP 容易把 Next.js 内联 style / style="" 属性挡掉，
        # 导致整个页面样式被清空（"紊乱/裸奔"），这里移除以保证样式完整。
        response = HTMLResponse(html)
        return response
    return JSONResponse({"error": "Not Found"}, status_code=404)


# 健康检查：自动打开浏览器前用它确认 HTTP 监听已就绪，避免"连接被拒绝"
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}

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

def _open_browser_later(url: str, timeout_sec: float = 30.0, interval: float = 0.5):
    """后台线程：等 uvicorn 真的能处理 HTTP 了再打开浏览器，避免 ERR_CONNECTION_REFUSED。"""
    import threading, time, webbrowser, os, sys, urllib.request, urllib.error, socket

    def _probe(health_url: str) -> bool:
        try:
            with urllib.request.urlopen(health_url, timeout=1.5) as r:
                return r.status == 200
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, socket.timeout, Exception):
            return False

    def _opener():
        # 从 URL 里拆出 /healthz
        try:
            from urllib.parse import urlparse
            p = urlparse(url)
            health_url = f"{p.scheme}://{p.netloc}/healthz"
        except Exception:
            health_url = url.rstrip("/") + "/healthz"

        deadline = time.time() + timeout_sec
        waited = 0.0
        while time.time() < deadline:
            if _probe(health_url):
                break
            time.sleep(interval)
            waited += interval
        else:
            print(
                f"[提示] 启动等待了 {int(waited)}s 仍未就绪，请手动访问: {url}",
                file=sys.stderr, flush=True,
            )
            return

        try:
            if os.name == "nt":
                os.startfile(url)
            else:
                webbrowser.open(url)
            print(
                f"[启动完成] 服务器就绪（{int(waited)}s），已打开浏览器: {url}",
                file=sys.stderr, flush=True,
            )
        except Exception as e:
            print(
                f"[提示] 自动打开浏览器失败（{e}），请手动访问: {url}",
                file=sys.stderr, flush=True,
            )

    threading.Thread(target=_opener, daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    HOST = "127.0.0.1"
    PORT = 8001
    HOME_URL = f"http://{HOST}:{PORT}/"

    # 只在首次启动（非 uvicorn reload 子进程）时打开浏览器，
    # 防止 reload 时每次代码改动都重新弹一个浏览器窗口。
    if os.environ.get("UVICORN_RELOAD") != "1":
        os.environ["UVICORN_RELOAD"] = "1"
        _open_browser_later(HOME_URL)

    # 启动命令：python -m app.main
    # reload=True 时必须排除数据库文件（*.db / *.db-shm / *.db-wal），
    # 否则 SQLite 每次写入都会触发 uvicorn 重载，导致网页间歇性无法访问。
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        reload_dirs=["app"],
        reload_excludes=["*.db", "*.db-*", "*.pyc", "__pycache__", "*.log"],
    )
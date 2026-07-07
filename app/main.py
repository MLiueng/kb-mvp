"""应用入口：创建 FastAPI 应用、挂载路由与静态资源、启动检查。

运行方式：
    python -m app.main
    或： uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import SERVER_PORT, STATIC_DIR, ensure_dirs, check_api_key


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    ensure_dirs()
    check_api_key()

    app = FastAPI(
        title="知识库系统 MVP",
        description="文档上传 → 解析分块 → 向量存储 → 检索增强生成（RAG）问答",
        version="1.0.0",
    )

    # 挂载 API 路由
    app.include_router(router)

    # 挂载静态资源目录
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # 根路径返回前端页面
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app


app = create_app()


if __name__ == "__main__":
    print()
    print("=" * 56)
    print("  知识库系统 MVP 启动中...")
    print(f"  访问地址: http://127.0.0.1:{SERVER_PORT}")
    print(f"  API 文档: http://127.0.0.1:{SERVER_PORT}/docs")
    print("=" * 56)
    print()
    uvicorn.run(app, host="127.0.0.1", port=SERVER_PORT)

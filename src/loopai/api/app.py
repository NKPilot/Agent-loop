"""loopAI 可观测性服务器的 FastAPI 应用工厂。

提供 create_app() 函数，用于组装 EventBus、CORS 中间件、
API 路由和生命周期管理。该应用设计为与现有 CLI 入口并行运行——
两者共享相同的 EventBus、Session 和工具基础设施。
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from loopai.events.bus import EventBus


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时：创建 EventBus 和会话注册表。
    关闭时：优雅地清理所有订阅者。
    """
    app.state.bus = EventBus()
    app.state.active_sessions: dict = {}
    yield
    await app.state.bus.shutdown()


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。

    Returns:
        完整配置的 FastAPI 应用，包含 CORS、生命周期和路由。
    """
    app = FastAPI(title="loopAI API", lifespan=lifespan)

    # Vite 开发服务器和本地开发的 CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API 路由 — stream、sessions 和 control 路由器
    from loopai.api.routes import control, sessions, stream  # noqa: E402

    app.include_router(stream.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(control.router, prefix="/api")

    # 静态文件：提供前端生产构建产物（通过 html=True 实现 SPA 回退）。
    # 必须在 API 路由之后挂载，以确保 /api/* 路径优先匹配。
    # 仅在前端 dist 目录存在时才挂载（开发期间不执行操作）。
    frontend_dist = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "frontend", "dist"
    )
    frontend_dist = os.path.abspath(frontend_dist)
    if os.path.isdir(frontend_dist):
        app.mount(
            "/",
            StaticFiles(directory=frontend_dist, html=True),
            name="frontend",
        )

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="0.0.0.0", port=8000)

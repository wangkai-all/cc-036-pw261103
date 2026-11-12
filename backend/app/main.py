"""FastAPI 入口。静态前端由 Vite 构建后放到 frontend/dist，由本服务托管。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import init_db
from .routers import intake, uploads

app = FastAPI(title="邮件接收台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 内网接收台；生产可按部署域名收敛
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(uploads.router)
app.include_router(intake.router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 托管构建后的 React 前端（存在时）
DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=DIST_DIR / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index = DIST_DIR / "index.html"
        return FileResponse(index)

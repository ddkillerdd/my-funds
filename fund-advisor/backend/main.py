"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.database import engine, Base
from backend.api.router import api_router
from backend.scheduler.jobs import setup_scheduler, job_startup_nav_check

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """管理应用启动和关闭，并允许本地环境禁用后台任务。"""
    # Startup
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    # Ensure upload directory exists
    Path("data/uploads").mkdir(parents=True, exist_ok=True)

    # 本地开发可关闭定时器，避免误调用外部数据源或邮件服务。
    sched = None
    if settings.ENABLE_SCHEDULER:
        sched = setup_scheduler()
        sched.start()
        logger.info("Scheduler started")

    # 启动回补单独控制，便于本地和测试环境完全隔离外部请求。
    if settings.ENABLE_STARTUP_NAV_CHECK:
        asyncio.create_task(job_startup_nav_check())

    yield

    # Shutdown
    if sched is not None:
        sched.shutdown()
        logger.info("Scheduler stopped")


app = FastAPI(
    title="基金持仓追踪器",
    description="Fund Portfolio Tracker API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router)


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "1.0.0"}

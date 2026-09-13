"""APScheduler job definitions for periodic tasks."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.database import SessionLocal
from backend.services.nav_service import NavService
from backend.services.snapshot_service import SnapshotService

logger = logging.getLogger(__name__)

# 所有本地调度窗口统一按中国标准时间解释。
SCHEDULER_TIMEZONE = ZoneInfo("Asia/Shanghai")
scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)

# Time after which today's NAV is expected to be available (24h format)
NAV_AVAILABLE_HOUR = 20


def _scheduler_now() -> datetime:
    """返回带上海时区的当前时间，供任务入口和测试统一注入。"""
    return datetime.now(SCHEDULER_TIMEZONE)


def _is_workday_candidate(job_name: str) -> bool:
    """在任务入口拦截周末，工作日仅表示候选调度窗口。"""
    current = _scheduler_now()
    if current.weekday() >= 5:
        logger.info("周末/工作日候选窗口：跳过 %s", job_name)
        return False
    return True


async def job_refresh_nav():
    """在工作日候选窗口刷新全部持仓净值。"""
    if not _is_workday_candidate("NAV 刷新"):
        return
    logger.info("Scheduled job: refreshing NAV for all funds")
    db = SessionLocal()
    try:
        result = await NavService(db).refresh_all_nav_smart()
        logger.info(f"NAV refresh result: {result}")
    except Exception as e:
        logger.error(f"NAV refresh failed: {e}")
    finally:
        db.close()


async def job_retry_nav():
    """在工作日候选窗口重试缺失净值。"""
    if not _is_workday_candidate("NAV 重试"):
        return
    logger.info("Scheduled job: retrying NAV for missing funds")
    db = SessionLocal()
    try:
        result = await NavService(db).refresh_all_nav_smart()
        logger.info(f"NAV retry result: {result}")
    except Exception as e:
        logger.error(f"NAV retry failed: {e}")
    finally:
        db.close()


async def job_daily_snapshot():
    """在工作日候选窗口创建日快照。"""
    if not _is_workday_candidate("日快照"):
        return
    logger.info("Scheduled job: creating daily snapshot")
    db = SessionLocal()
    try:
        snapshot = SnapshotService(db).create_daily_snapshot()
        logger.info(f"Snapshot created: {snapshot.snapshot_date}, MV={snapshot.total_market_value}")
    except Exception as e:
        logger.error(f"Snapshot creation failed: {e}")
    finally:
        db.close()


async def job_startup_nav_check():
    """On startup: fetch NAV data intelligently.

    Logic:
    1. If any active fund has no NAV data at all → fetch regardless of time/weekday.
    2. Otherwise, use smart refresh:
       - Fetch latest trading day NAV first (highest priority)
       - Background task will fill in any missing dates
    """
    db = SessionLocal()
    try:
        svc = NavService(db)

        # Step 1: funds completely missing NAV data (no history at all)
        status = svc.get_nav_status()
        if status["funds_missing_nav"] > 0:
            logger.info(
                f"Startup NAV check: {status['funds_missing_nav']} fund(s) have no NAV "
                "data at all, fetching now..."
            )
            result = await svc.refresh_all_nav_smart()
            logger.info(f"Startup NAV fetch result: {result}")
            return

        # Step 2: smart refresh - get latest trading day and backfill missing dates
        latest_trading = svc.get_latest_trading_date()
        if latest_trading:
            logger.info(
                f"Startup NAV check: latest trading day is {latest_trading}, "
                "using smart refresh to get latest NAV and backfill missing dates..."
            )
            result = await svc.refresh_all_nav_smart()
            logger.info(f"Startup NAV smart refresh result: {result}")
        else:
            logger.info("Startup NAV check: no trading data found, skipping")

    except Exception as e:
        logger.error(f"Startup NAV check failed: {e}")
    finally:
        db.close()


def setup_scheduler():
    """Configure and return the scheduler with all jobs."""
    # Weekday NAV refresh at 20:00
    scheduler.add_job(
        job_refresh_nav,
        CronTrigger(
            day_of_week="mon-fri",
            hour=20,
            minute=0,
            timezone=SCHEDULER_TIMEZONE,
        ),
        id="refresh_nav",
        replace_existing=True,
    )

    # Weekday NAV retry at 22:00
    scheduler.add_job(
        job_retry_nav,
        CronTrigger(
            day_of_week="mon-fri",
            hour=22,
            minute=0,
            timezone=SCHEDULER_TIMEZONE,
        ),
        id="retry_nav",
        replace_existing=True,
    )

    # Weekday snapshot at 22:30
    scheduler.add_job(
        job_daily_snapshot,
        CronTrigger(
            day_of_week="mon-fri",
            hour=22,
            minute=30,
            timezone=SCHEDULER_TIMEZONE,
        ),
        id="daily_snapshot",
        replace_existing=True,
    )

    return scheduler

"""Scheduler API - manual trigger for background jobs."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.email_send_record import EmailSendRecord  # noqa: F401  (注册模型供 Alembic 使用)

router = APIRouter()


@router.post("/run-advisor")
def run_advisor_job(
    push_email: bool = Query(
        False,
        description="本地邮件已禁用，必须为 false；交易日邮件由 OpenClaw 负责",
    ),
    model: Optional[str] = Query(
        None,
        description="兼容参数；留空时使用服务器统一模型配置",
    ),
    force: bool = Query(
        False,
        description="本地邮件已禁用，必须为 false；不得绕过去重边界",
    ),
    read_only: bool = Query(
        False,
        description="true 会被明确拒绝；false 仍是可能写入数据库并调用外部模型的正常业务任务",
    ),
    db: Session = Depends(get_db),
):
    """手动生成顾问报告。

    该 POST 不是只读巡检，也不是健康检查；可能写入 AdvisorReport、AdviceSnapshot、
    FactorHitRate，并可能调用外部模型。本地邮件仍由 OpenClaw 责任边界控制。
    read_only=true 会在任何业务调用前返回 400。
    """
    from backend.scheduler.advisor_job import AdvisorJob
    read_only_flag = read_only is True
    try:
        result = AdvisorJob(
            db,
            push_email=push_email,
            model=model,
            force=force,
            read_only=read_only_flag,
        ).run()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result

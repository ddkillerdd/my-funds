"""Advisor API endpoints - AI-powered portfolio analysis with persistence."""

import json
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import get_db
from backend.models.advisor_report import AdvisorReport

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_MODEL = "stepfun-ai/step-3.7-flash"

# 最大保留报告数（超过时删除最旧的）
MAX_REPORTS = 30

CST = timezone(timedelta(hours=8))


def _to_cst(naive_utc_dt: datetime) -> str:
    """将 naive UTC datetime 转为 Asia/Shanghai ISO 时间字符串。"""
    if naive_utc_dt is None:
        return ""
    if naive_utc_dt.tzinfo is None:
        cst = naive_utc_dt.replace(tzinfo=timezone.utc).astimezone(CST)
    else:
        cst = naive_utc_dt.astimezone(CST)
    return cst.strftime("%Y-%m-%d %H:%M:%S")


@router.post("/analyze")
def analyze_portfolio(
    model: str = Query(DEFAULT_MODEL, description="LLM model for analysis (v2 only)"),
    engine: str = Query("v3", description="Engine: v3 (FundAnalyzer, default) or v2 (legacy)"),
    db: Session = Depends(get_db),
):
    """Run a full AI-powered portfolio analysis and persist the result."""
    from backend.services.advisor_service import AdvisorService
    result = AdvisorService(db).analyze(model=model, engine=engine)

    # Persist to database
    report = AdvisorReport(
        report_json=json.dumps(result, ensure_ascii=False),
        model_used=result.get("model", model),
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # 清理旧报告，只保留最近的 MAX_REPORTS 份
    total = db.query(AdvisorReport).count()
    if total > MAX_REPORTS:
        to_delete = total - MAX_REPORTS
        ids_to_delete = (
            db.query(AdvisorReport.id)
            .order_by(AdvisorReport.created_at.asc())
            .limit(to_delete)
            .all()
        )
        delete_ids = [r[0] for r in ids_to_delete]
        db.query(AdvisorReport).filter(AdvisorReport.id.in_(delete_ids)).delete(synchronize_session=False)
        db.commit()
        logger.info(f"Cleaned {to_delete} old report(s), kept last {MAX_REPORTS}")

    logger.info(f"Advisor report saved (id={report.id}, model={report.model_used})")
    return result


@router.get("/report")
def get_latest_report(
    db: Session = Depends(get_db),
):
    """Get the latest persisted analysis report."""
    report = db.query(AdvisorReport).order_by(desc(AdvisorReport.created_at)).first()
    if not report:
        return {
            "found": False,
            "report": None,
            "message": "暂无已保存的分析报告",
        }
    try:
        data = json.loads(report.report_json)
    except json.JSONDecodeError:
        return {
            "found": False,
            "report": None,
            "message": "已保存的报告数据异常",
        }
    return {
        "found": True,
        "report": data,
        "generated_at": _to_cst(report.created_at),
        "model": report.model_used,
    }


@router.get("/reports")
def list_reports(
    skip: int = Query(0, ge=0, description="分页偏移"),
    limit: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
):
    """Get a paginated list of all persisted reports (metadata only, no full JSON)."""
    total = db.query(AdvisorReport).count()
    rows = (
        db.query(AdvisorReport.id, AdvisorReport.model_used, AdvisorReport.created_at)
        .order_by(desc(AdvisorReport.created_at))
        .offset(skip)
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": r.id,
            "model": r.model_used,
            "created_at": _to_cst(r.created_at),
        }
        for r in rows
    ]
    return {"total": total, "items": items, "skip": skip, "limit": limit}


@router.get("/report/{report_id}")
def get_report_by_id(
    report_id: int,
    db: Session = Depends(get_db),
):
    """Get a specific persisted report by ID."""
    report = db.query(AdvisorReport).filter(AdvisorReport.id == report_id).first()
    if not report:
        return {
            "found": False,
            "report": None,
            "message": f"报告 {report_id} 不存在",
        }
    try:
        data = json.loads(report.report_json)
    except json.JSONDecodeError:
        return {
            "found": False,
            "report": None,
            "message": "该报告数据异常",
        }
    return {
        "found": True,
        "report": data,
        "generated_at": _to_cst(report.created_at),
        "model": report.model_used,
    }


@router.get("/status")
def advisor_status(db: Session = Depends(get_db)):
    """Check if advisor service is available."""
    from backend.config import get_settings
    settings = get_settings()

    # Check if there's a persisted report
    last_report = db.query(AdvisorReport).order_by(desc(AdvisorReport.created_at)).first()

    return {
        "configured": bool(settings.NEWAPI_BASE_URL and settings.NEWAPI_API_KEY),
        "api_base": settings.NEWAPI_BASE_URL or "",
        "default_model": DEFAULT_MODEL,
        "has_report": last_report is not None,
        "last_report_at": _to_cst(last_report.created_at) if last_report else None,
        "last_report_id": last_report.id if last_report else None,
    }

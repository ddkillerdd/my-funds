"""Advisor API endpoints - AI-powered portfolio analysis with persistence."""

import json
import logging
from datetime import date, datetime, timezone, timedelta

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


def _patch_report_actions(data: dict) -> dict:
    """补全 actions 中空的 fund_name（兼容旧报告）。"""
    if not data.get('actions'):
        return data
    fund_names = {fd.get('fund_code'): fd.get('fund_name', fd.get('fund_code', ''))
                  for fd in data.get('per_fund_diagnosis', [])}
    for a in data['actions']:
        if not a.get('fund_name') and a.get('fund_code'):
            a['fund_name'] = fund_names.get(a['fund_code'], a['fund_code'])
    return data


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

    # RFC-012: 建议回测快照（报告已入库，可关联 report_id）
    try:
        from backend.services.backtest_service import BacktestService
        bsvc = BacktestService(db)
        # 从已保存的报告 JSON 里提取 actions + 建议时净值，写入 advice_snapshot
        saved = json.loads(report.report_json)
        actions = [
            {
                "fund_code": a.get("fund_code"),
                "fund_name": a.get("fund_name"),
                "action": a.get("action"),
                "change_pct": a.get("change_pct"),
            }
            for a in (saved.get("actions") or [])
            if a.get("fund_code") and a.get("action")
        ]
        # 建议时净值：用报告里的 per_fund_diagnosis 或回退到净值表
        navs = {}
        for fd in (saved.get("per_fund_diagnosis") or []):
            # v3 使用 quant，兼容历史报告中的 quant_indicator。
            q = fd.get("quant") or fd.get("quant_indicator") or {}
            if fd.get("fund_code") and q.get("nav") is not None:
                navs[fd["fund_code"]] = q["nav"]
        bsvc.record_advice(
            report_id=report.id,
            advice_date=date.today(),
            actions=actions,
            fund_navs=navs,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("backtest record_advice failed: %s", e)

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
    data = _patch_report_actions(data)
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
    
    data = _patch_report_actions(data)
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

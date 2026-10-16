"""Advisor API endpoints - AI-powered portfolio analysis with persistence."""

import json
import logging
from datetime import date, datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import get_db
from backend.models.advisor_report import AdvisorReport
from backend.schemas.purchase_confirmation import PurchaseConfirmation

logger = logging.getLogger(__name__)

router = APIRouter()

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
    model: str | None = Query(None, description="兼容参数；v3 使用服务器统一模型配置"),
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
    # 新生成报告也立即返回主键，方便用户当天回填实际执行金额。
    result["report_id"] = report.id
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
        "default_model": settings.ANALYZER_PRIMARY_MODEL,
        "has_report": last_report is not None,
        "last_report_at": _to_cst(last_report.created_at) if last_report else None,
        "last_report_id": last_report.id if last_report else None,
    }


@router.get("/report/{report_id}/mail-preview", summary="只读生成既有报告的安全邮件预览，不发送")
def preview_report_mail(report_id: int, db: Session = Depends(get_db)):
    """只读取既有报告，必要时重查预算与渠道；不调用分析、SMTP或任何写入。"""
    from backend.services.decision_delivery_service import build_delivery_preview
    from backend.services.execution_policy import apply_execution_policy_from_db, fail_closed_execution_policy

    row = db.query(AdvisorReport).filter(AdvisorReport.id == report_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    try:
        saved = json.loads(row.report_json)
        if not isinstance(saved, dict):
            raise ValueError("报告格式异常")
        actions = saved.get("actions") or []
        if not isinstance(actions, list) or any(not isinstance(item, dict) or isinstance(item.get("action_amount"), bool) for item in actions):
            raise ValueError("报告动作格式异常")
        # 预算复算只能进一步收紧；不能将原门禁已拦截的异常正数重新放行。
        for item in actions:
            if item.get("policy_status") == "blocked":
                item["action_amount"] = 0.0
        clock = datetime.now(CST)
        original_gate = (saved.get("execution_policy") or {}).get("purchase_channel_gate") is True
        rechecked = False
        if original_gate:
            try:
                saved = apply_execution_policy_from_db(db, saved, now=clock)
                rechecked = True
            except Exception:
                saved = fail_closed_execution_policy(saved, "budget_not_rechecked")
        return build_delivery_preview(saved, row.id, row.created_at, now=clock, budget_rechecked=rechecked)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="报告格式异常，无法生成安全预览") from None


@router.get("/purchase-options/public", summary="只读查询当前四只持仓的公开销售状态，不确认账户可买")
def public_purchase_options(db: Session = Depends(get_db)):
    """只读取有效持仓代码和固定公开来源，不读取账户凭据或写入渠道快照。"""
    from backend.models.holding import FundHolding
    from backend.services.public_purchase_source import fetch_current_public_options

    rows = db.query(FundHolding.fund_code).filter(FundHolding.status == 1).distinct().all()
    return {
        "items": fetch_current_public_options([row[0] for row in rows]),
        "readonly": True, "account_verified": False, "is_trade_instruction": False,
        "message": "仅为公开渠道线索；账户资格、实际优惠和剩余额度仍需下单前确认。",
    }


@router.post('/report/{report_id}/purchase-preview', summary='当次确认下单页后只读试算，不保存或交易')
def preview_confirmed_purchase(report_id: int, body: PurchaseConfirmation, db: Session = Depends(get_db)):
    """只读当前报告、有效代码及实际预算，手动信息仅在本次请求内有效。"""
    from backend.models.holding import FundHolding
    from backend.services.decision_delivery_service import build_delivery_preview
    from backend.services.execution_policy import apply_execution_policy_from_db
    from backend.services.public_purchase_source import SUPPORTED_CODES
    from backend.services.purchase_confirmation_service import confirmation_valid_until, prepare_confirmation_report

    row = db.query(AdvisorReport).filter(AdvisorReport.id == report_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail='报告不存在')
    rows = db.query(FundHolding.fund_code).filter(FundHolding.status == 1).distinct().all()
    active_codes = {item[0] for item in rows} & SUPPORTED_CODES
    if body.fund_code not in active_codes:
        raise HTTPException(status_code=422, detail='仅支持当前四只有效持仓，不自动添加基金')
    try:
        saved = prepare_confirmation_report(json.loads(row.report_json), body.fund_code)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=409, detail='该报告不支持当次确认，请使用新版当天报告') from None
    clock = datetime.now(CST)
    try:
        checked = apply_execution_policy_from_db(db, saved, now=clock, confirmed_quotes=[body.as_quote()])
        for previous, action in zip(saved['actions'], checked['actions']):
            if previous.get('policy_status') == 'blocked' and previous.get('policy_reasons') != ['purchase_channel_unverified']:
                action.update(action_amount=0.0, policy_status='blocked', policy_reasons=previous.get('policy_reasons'))
        result = build_delivery_preview(checked, row.id, row.created_at, now=clock, budget_rechecked=True)
        result['valid_until'] = confirmation_valid_until(row.created_at, body.observed_at, clock).isoformat()
    except Exception:
        # 不输出数据库错误、用户输入全文或账户相关信息；失败时没有可执行金额。
        raise HTTPException(status_code=503, detail='只读复核未完成，不操作；未保存或下单') from None
    result.update(
        confirmation_saved=False, confirmation_kind='requester_attested_only',
        account_ownership_verified=False, source_verified_by_platform_api=False,
        decision_scope='本次请求的手动确认预览，不更改日报、邮件或已保存报告',
    )
    return result

"""定时顾问任务：生成分析结果并披露完整操作边界。

本模块可由以下入口触发：
1. OpenClaw cron（首选）——交易日邮件投递由 OpenClaw 负责；
2. 直接 API 调用——POST /api/scheduler/run-advisor。

正常路径可能持久化报告（AdvisorReport/AdviceSnapshot）、验证样本、可能更新回测统计
（FactorHitRate），也可能调用外部模型。本地 fund-advisor 邮件路径已禁用，真实 QQ/邮件
投递和去重由 OpenClaw 负责。
"""

import json
import logging
from datetime import datetime, date
from typing import Optional

from sqlalchemy.orm import Session

from backend.services.advisor_service import AdvisorService
from backend.models.advisor_report import AdvisorReport

logger = logging.getLogger(__name__)

MAX_REPORTS = 30  # 与 api/advisor.py 保持一致，最多保留最近报告份数
OPERATION_SCOPE = "advisor_analysis_with_persistence_and_backtest_updates"


class AdvisorJob:
    """Run AI portfolio analysis and push results."""

    def __init__(self, db: Session, push_email: bool = False, model: Optional[str] = None, force: bool = False, persist_report: bool = True, read_only: bool = False):
        """初始化顾问任务；未指定模型时使用统一的主模型配置。"""
        from backend.config import get_settings

        self.db = db
        self.push_email = push_email
        self.model = model or get_settings().ANALYZER_PRIMARY_MODEL
        self.force = force
        self.persist_report = persist_report
        self.read_only = read_only
        self.report_id = None  # 本次运行保存的 advisor_report.id（供调用方/cron 获取）

    def _today_cst(self) -> date:
        """Return the current calendar date in Asia/Shanghai (UTC+8)."""
        from datetime import timezone, timedelta
        return datetime.now(timezone(timedelta(hours=8))).date()

    def _persist_report(self, result: dict) -> None:
        """保存分析报告到 advisor_report（与 POST /api/advisor/analyze 一致）。

        写入报告 + RFC-012 建议回测快照 + 清理旧报告（保留最近 MAX_REPORTS 份）。
        任何失败都不阻断主流程（只记日志，不影响发邮件）。
        """
        try:
            report = AdvisorReport(
                report_json=json.dumps(result, ensure_ascii=False),
                model_used=result.get("model", self.model),
            )
            self.db.add(report)
            self.db.commit()
            self.db.refresh(report)

            # RFC-012: 建议回测快照（关联 report_id）
            try:
                from backend.services.backtest_service import BacktestService
                bsvc = BacktestService(self.db)
                actions = [
                    {
                        "fund_code": a.get("fund_code"),
                        "fund_name": a.get("fund_name"),
                        "action": a.get("action"),
                        "change_pct": a.get("change_pct"),
                    }
                    for a in (result.get("actions") or [])
                    if a.get("fund_code") and a.get("action")
                ]
                navs = {}
                for fd in (result.get("per_fund_diagnosis") or []):
                    # v3 使用 quant，兼容历史报告中的 quant_indicator。
                    q = fd.get("quant") or fd.get("quant_indicator") or {}
                    if fd.get("fund_code") and q.get("nav") is not None:
                        navs[fd["fund_code"]] = q["nav"]
                bsvc.record_advice(
                    report_id=report.id,
                    advice_date=self._today_cst(),
                    actions=actions,
                    fund_navs=navs,
                )
            except Exception as e:  # noqa: BLE001
                self.db.rollback()
                logger.warning("backtest record_advice failed in advisor job: %s", e)

            # 清理旧报告，只保留最近 MAX_REPORTS 份
            from sqlalchemy import desc
            total = self.db.query(AdvisorReport).count()
            if total > MAX_REPORTS:
                to_delete = total - MAX_REPORTS
                # 按(创建时间, id)倒序，跳过最新的 MAX_REPORTS 份，剩下的即最旧的待删记录
                ids_to_delete = (
                    self.db.query(AdvisorReport.id)
                    .order_by(desc(AdvisorReport.created_at), desc(AdvisorReport.id))
                    .offset(MAX_REPORTS)
                    .all()
                )
                delete_ids = [r[0] for r in ids_to_delete[:to_delete]]
                self.db.query(AdvisorReport).filter(
                    AdvisorReport.id.in_(delete_ids)
                ).delete(synchronize_session=False)
                self.db.commit()
                logger.info(
                    "Cleaned %d old report(s) in advisor job, kept last %d", to_delete, MAX_REPORTS
                )

            logger.info("Advisor report saved (id=%s, model=%s) [from advisor job]", report.id, report.model_used)
            self.report_id = report.id
        except Exception as e:  # noqa: BLE001
            self.db.rollback()
            logger.warning("persist report failed in advisor job: %s", e)

    def run(self) -> dict:
        """
        执行一次有明确副作用边界的顾问分析周期。

        read_only=True 目前不支持，会在任何分析、数据库、回测或外部调用前拒绝。
        """
        if self.read_only is True:
            raise ValueError(
                "当前 run-advisor 不支持只读模式；push_email=false 仅关闭本地邮件；"
                "请使用已核实的 GET/受控只读查询"
            )
        if self.push_email or self.force:
            raise ValueError(
                "本地邮件已禁用；交易日邮件责任属于 OpenClaw，"
                "push_email 和 force 必须为 false"
            )

        start_time = datetime.now()
        logger.info("AdvisorJob started at {time}".format(time=start_time.isoformat()))

        # Step 1: Run AI analysis
        result = AdvisorService(self.db).analyze(model=self.model)
        analysis_success = ("portfolio_diagnosis" in result
                           and result.get("portfolio_diagnosis", {}).get("overall_assessment") != "无法分析")
        # Check if fallback
        assessment = result.get("portfolio_diagnosis", {}).get("overall_assessment", "")
        is_fallback = ("无法分析" in assessment or "暂不可用" in assessment)

        # Step 1.5: 持久化报告到 advisor_report（与 POST /api/advisor/analyze 行为一致，
        # 让定时任务/手动 run-advisor 的报告也能在前端回溯、计入 RFC-012 回测命中率）
        if self.persist_report:
            self._persist_report(result)

        # Step 2: RFC-012 回测验证 + 在线学习适应（每日顺带跑，10天自动收紧置信度）
        backtest = {"validated": 0, "adapted": False}
        try:
            from backend.services.backtest_service import BacktestService
            bsvc = BacktestService(self.db)
            backtest["validated"] = bsvc.validate_due()
            # 定期适应：满 10 个样本后每跑一次 refresh，可能提交命中率更新。
            adapted = bsvc.refresh_hit_rates(rolling_window=10)
            backtest["adapted"] = adapted > 0
            fb = bsvc.get_feedback()
            backtest["has_evidence"] = fb.has_evidence
            backtest["prompt_hint"] = fb.prompt_hint
        except Exception as e:  # noqa: BLE001
            logger.warning("backtest adapt failed in daily job: %s", e)
            backtest["error"] = str(e)

        # Step 3: Build summary
        backtest_updates_enabled = True
        operation_contract = {
            "operation_scope": OPERATION_SCOPE,
            "read_only": False,
            "report_persistence_enabled": bool(self.persist_report),
            "backtest_updates_enabled": backtest_updates_enabled,
            "database_writes_possible": bool(self.persist_report) or backtest_updates_enabled,
            "external_model_calls_enabled": True,
            "local_email_disabled": True,
            "email_owner": "OpenClaw",
        }
        summary = {
            "analysis_ok": analysis_success and not is_fallback,
            "holding_count": len(result.get("holdings_health", [])),
            "actions_count": len(result.get("actions", [])),
            "email_sent": False,
            "email_owner": "OpenClaw",
            "local_email_disabled": True,
            "skipped": False,
            "started_at": start_time.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "model": self.model,
            "report_id": self.report_id,
            "backtest": backtest,
            **operation_contract,
        }

        return {
            "success": analysis_success,
            "is_fallback": is_fallback,
            "analysis": result,
            "email_sent": False,
            "email_owner": "OpenClaw",
            "local_email_disabled": True,
            "skipped": False,
            "summary": summary,
            **operation_contract,
        }

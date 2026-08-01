"""Scheduled advisor job - runs AI analysis and pushes report by email.

This module is designed to be triggered by:
1. OpenClaw cron (preferred) - systemd timer or OpenClaw scheduler
2. Direct API call - POST /api/scheduler/run-advisor

Concurrency guard:
  A daily dedupe lock (`email_send_record`) ensures we never send more than ONE
  advisor email per calendar day, even if the same job is fired multiple times
  (e.g. OpenClaw cron timeout/retry). Pass force=True to bypass the lock.
"""

import json
import logging
from datetime import datetime, date

from sqlalchemy.orm import Session

from backend.services.advisor_service import AdvisorService
from backend.services.mail_service import MailService
from backend.models.email_send_record import EmailSendRecord
from backend.models.advisor_report import AdvisorReport

logger = logging.getLogger(__name__)

MAX_REPORTS = 30  # 与 api/advisor.py 保持一致，最多保留最近报告份数


class AdvisorJob:
    """Run AI portfolio analysis and push results."""

    def __init__(self, db: Session, push_email: bool = True, model: str = "stepfun-ai/step-3.7-flash", force: bool = False, persist_report: bool = True):
        self.db = db
        self.push_email = push_email
        self.model = model
        self.force = force
        self.persist_report = persist_report
        self.report_id = None  # 本次运行保存的 advisor_report.id（供调用方/cron 获取）

    def _today_cst(self) -> date:
        """Return the current calendar date in Asia/Shanghai (UTC+8)."""
        from datetime import timezone, timedelta
        return datetime.now(timezone(timedelta(hours=8))).date()

    def _already_sent_today(self) -> bool:
        """True if an advisor email was already recorded for today."""
        return self.db.query(EmailSendRecord).filter(
            EmailSendRecord.report_date == self._today_cst()
        ).first() is not None

    def _mark_sent(self) -> None:
        """Record that an email was sent today. Unique constraint guards races."""
        self.db.add(EmailSendRecord(report_date=self._today_cst(), model_used=self.model))
        try:
            self.db.commit()
        except Exception:
            # A concurrent run already inserted today's row → dedupe is fine.
            self.db.rollback()

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
                    q = fd.get("quant_indicator", {})
                    if fd.get("fund_code") and q.get("nav"):
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
        Execute one analysis cycle. Only one email per calendar day by default.

        Returns:
            dict with keys: success, analysis, email_sent, summary, skipped
        """
        start_time = datetime.now()
        logger.info("AdvisorJob started at {time}".format(time=start_time.isoformat()))

        today = self._today_cst()
        dedupe_active = self.push_email and not self.force
        if dedupe_active and self._already_sent_today():
            logger.info("AdvisorJob skipped: email already sent today (%s). force=%s", today, self.force)
            return {
                "success": True,
                "skipped": True,
                "skip_reason": f"email already sent today ({today}); use force=true to override",
                "analysis": None,
                "email_sent": False,
                "summary": {
                    "analysis_ok": False,
                    "skipped": True,
                    "holding_count": 0,
                    "actions_count": 0,
                    "email_sent": False,
                    "started_at": start_time.isoformat(),
                    "finished_at": datetime.now().isoformat(),
                    "model": self.model,
                },
            }

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

        # Step 2: Send email (respect daily dedupe lock)
        email_sent = False
        if self.push_email and not is_fallback:
            mail = MailService()
            if mail.configured:
                email_sent = mail.send_analysis_report(result)
                if email_sent:
                    self._mark_sent()
            else:
                logger.warning("Mail service not configured, skipping email")

        # Step 2.5: RFC-012 回测验证 + 在线学习适应（每日顺带跑，10天自动收紧置信度）
        backtest = {"validated": 0, "adapted": False}
        try:
            from backend.services.backtest_service import BacktestService
            bsvc = BacktestService(self.db)
            backtest["validated"] = bsvc.validate_due()
            # 定期适应：满 10 个样本后每跑一次 refresh（幂等、无副作用）
            adapted = bsvc.refresh_hit_rates(rolling_window=10)
            backtest["adapted"] = adapted > 0
            fb = bsvc.get_feedback()
            backtest["has_evidence"] = fb.has_evidence
            backtest["prompt_hint"] = fb.prompt_hint
        except Exception as e:  # noqa: BLE001
            logger.warning("backtest adapt failed in daily job: %s", e)
            backtest["error"] = str(e)

        # Step 3: Build summary
        summary = {
            "analysis_ok": analysis_success and not is_fallback,
            "holding_count": len(result.get("holdings_health", [])),
            "actions_count": len(result.get("actions", [])),
            "email_sent": email_sent,
            "skipped": False,
            "started_at": start_time.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "model": self.model,
            "report_id": self.report_id,
            "backtest": backtest,
        }

        return {
            "success": analysis_success,
            "is_fallback": is_fallback,
            "analysis": result,
            "email_sent": email_sent,
            "skipped": False,
            "summary": summary,
        }

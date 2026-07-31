"""Scheduled advisor job - runs AI analysis and pushes report by email.

This module is designed to be triggered by:
1. OpenClaw cron (preferred) - systemd timer or OpenClaw scheduler
2. Direct API call - POST /api/scheduler/run-advisor

Concurrency guard:
  A daily dedupe lock (`email_send_record`) ensures we never send more than ONE
  advisor email per calendar day, even if the same job is fired multiple times
  (e.g. OpenClaw cron timeout/retry). Pass force=True to bypass the lock.
"""

import logging
from datetime import datetime, date

from sqlalchemy.orm import Session

from backend.services.advisor_service import AdvisorService
from backend.services.mail_service import MailService
from backend.models.email_send_record import EmailSendRecord

logger = logging.getLogger(__name__)


class AdvisorJob:
    """Run AI portfolio analysis and push results."""

    def __init__(self, db: Session, push_email: bool = True, model: str = "stepfun-ai/step-3.7-flash", force: bool = False):
        self.db = db
        self.push_email = push_email
        self.model = model
        self.force = force

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
        }

        return {
            "success": analysis_success,
            "is_fallback": is_fallback,
            "analysis": result,
            "email_sent": email_sent,
            "skipped": False,
            "summary": summary,
        }

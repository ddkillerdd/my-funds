"""Scheduled advisor job - runs AI analysis and pushes report by email.

This module is designed to be triggered by:
1. OpenClaw cron (preferred) - systemd timer or OpenClaw scheduler
2. Direct API call - POST /api/scheduler/run-advisor
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.services.advisor_service import AdvisorService
from backend.services.mail_service import MailService

logger = logging.getLogger(__name__)


class AdvisorJob:
    """Run AI portfolio analysis and push results."""

    def __init__(self, db: Session, push_email: bool = True, model: str = "stepfun-ai/step-3.7-flash"):
        self.db = db
        self.push_email = push_email
        self.model = model

    def run(self) -> dict:
        """
        Execute one analysis cycle.

        Returns:
            dict with keys: success, analysis, email_sent, summary
        """
        start_time = datetime.now()
        logger.info("AdvisorJob started at {time}".format(time=start_time.isoformat()))

        # Step 1: Run AI analysis
        result = AdvisorService(self.db).analyze(model=self.model)
        analysis_success = ("portfolio_diagnosis" in result
                           and result.get("portfolio_diagnosis", {}).get("overall_assessment") != "无法分析")
        # Check if fallback
        is_fallback = (result.get("portfolio_diagnosis", {}).get("overall_assessment", "")
                       and "暂不可用" in result.get("portfolio_diagnosis", {}).get("overall_assessment", ""))

        # Step 2: Send email
        email_sent = False
        if self.push_email and not is_fallback:
            mail = MailService()
            if mail.configured:
                email_sent = mail.send_analysis_report(result)
            else:
                logger.warning("Mail service not configured, skipping email")

        # Step 3: Build summary
        summary = {
            "analysis_ok": analysis_success and not is_fallback,
            "holding_count": len(result.get("holdings_health", [])),
            "actions_count": len(result.get("actions", [])),
            "email_sent": email_sent,
            "started_at": start_time.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "model": self.model,
        }

        return {
            "success": analysis_success,
            "is_fallback": is_fallback,
            "analysis": result,
            "email_sent": email_sent,
            "summary": summary,
        }

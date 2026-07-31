"""Scheduler API - manual trigger for background jobs."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.email_send_record import EmailSendRecord  # noqa: F401  (register table for create_all)

router = APIRouter()


@router.post("/run-advisor")
def run_advisor_job(
    push_email: bool = Query(True, description="Send email with report"),
    model: str = Query("stepfun-ai/step-3.7-flash", description="LLM model"),
    force: bool = Query(False, description="Bypass the once-per-day email dedupe lock"),
    db: Session = Depends(get_db),
):
    """Manually trigger the advisor job (AI analysis + optional email push).

    Only one email is sent per calendar day by default (daily dedupe lock).
    Pass force=true to force a fresh analysis + email regardless of the lock.
    """
    from backend.scheduler.advisor_job import AdvisorJob
    result = AdvisorJob(db, push_email=push_email, model=model, force=force).run()
    return result

"""Scheduler API - manual trigger for background jobs."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db

router = APIRouter()


@router.post("/run-advisor")
def run_advisor_job(
    push_email: bool = Query(True, description="Send email with report"),
    model: str = Query("stepfun-ai/step-3.7-flash", description="LLM model"),
    db: Session = Depends(get_db),
):
    """Manually trigger the advisor job (AI analysis + optional email push)."""
    from backend.scheduler.advisor_job import AdvisorJob
    result = AdvisorJob(db, push_email=push_email, model=model).run()
    return result

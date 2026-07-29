"""Advisor API endpoints - AI-powered portfolio analysis."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.database import get_db

router = APIRouter()


@router.post("/analyze")
def analyze_portfolio(
    model: str = Query("stepfun-ai/step-3.7-flash", description="LLM model for analysis"),
    db: Session = Depends(get_db),
):
    """Run a full AI-powered portfolio analysis."""
    from backend.services.advisor_service import AdvisorService
    result = AdvisorService(db).analyze(model=model)
    return result


@router.get("/status")
def advisor_status(db: Session = Depends(get_db)):
    """Check if advisor service is available."""
    from backend.config import get_settings
    settings = get_settings()
    return {
        "configured": bool(settings.NEWAPI_BASE_URL and settings.NEWAPI_API_KEY),
        "api_base": settings.NEWAPI_BASE_URL or "",
        "default_model": "stepfun-ai/step-3.7-flash",
    }

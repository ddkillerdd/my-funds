"""Holdings API endpoints."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.schemas.holding_change import HoldingChangeResponse as OperationChangeResponse
from backend.schemas.holding import HoldingResponse, HoldingsByPlatformResponse, HoldingCostUpdate, HoldingCreate, HoldingDeleteResponse, SimpleImportRequest, SimpleImportResult, HoldingChangeRequest, HoldingChangeResponse, SimpleImportPreviewRequest, SimpleImportPreviewResponse

router = APIRouter()


@router.get("", response_model=list[HoldingResponse])
def get_holdings(
    platform: Optional[str] = Query(None, description="Filter by platform"),
    search: Optional[str] = Query(None, description="Search by fund code or name"),
    sort_by: str = Query("market_value", description="Sort field"),
    sort_order: str = Query("desc", description="asc or desc"),
    db: Session = Depends(get_db),
):
    """Get all active holdings with optional filters."""
    from backend.services.holding_service import HoldingService
    return HoldingService(db).get_holdings(
        platform=platform, search=search, sort_by=sort_by, sort_order=sort_order
    )


@router.get("/by-platform", response_model=list[HoldingsByPlatformResponse])
def get_holdings_by_platform(db: Session = Depends(get_db)):
    """Get holdings grouped by platform."""
    from backend.services.holding_service import HoldingService
    return HoldingService(db).get_holdings_by_platform()


@router.get("/platforms", response_model=list[str])
def get_platforms(db: Session = Depends(get_db)):
    """Get all distinct platform names."""
    from backend.services.holding_service import HoldingService
    return HoldingService(db).get_platforms()


@router.patch("/{holding_id}", response_model=HoldingResponse)
def update_holding_cost(
    holding_id: int,
    body: HoldingCostUpdate,
    db: Session = Depends(get_db),
):
    """Update cost_nav for a holding."""
    from backend.services.holding_service import HoldingService
    try:
        return HoldingService(db).update_cost(holding_id, body.cost_nav)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("", response_model=HoldingResponse, status_code=201)
def create_holding(
    body: HoldingCreate,
    db: Session = Depends(get_db),
):
    """Create a new manual holding entry."""
    from backend.services.holding_service import HoldingService
    return HoldingService(db).create_holding(body)


@router.delete("/{holding_id}", response_model=HoldingDeleteResponse)
def delete_holding(
    holding_id: int,
    db: Session = Depends(get_db),
):
    """Soft delete (set status=0) a holding."""
    from backend.services.holding_service import HoldingService
    try:
        return HoldingService(db).delete_holding(holding_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{holding_id}/change", response_model=HoldingChangeResponse)
def change_holding(
    holding_id: int,
    body: HoldingChangeRequest,
    db: Session = Depends(get_db),
):
    """RFC-011: Record an add/increase or reduce/decrease by RMB amount.

    Writes a holding_changes record and updates the live holding,
    so the next analysis reflects the true portfolio.
    """
    from backend.services.holding_service import HoldingService
    try:
        return HoldingService(db).record_change(holding_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/simple-import", response_model=SimpleImportResult)
def simple_import(
    body: SimpleImportRequest,
    db: Session = Depends(get_db),
):
    """Quick import: fund_code + market_value only.

    Auto-resolves fund name, looks up latest NAV,
    and calculates shares automatically.
    """
    from backend.services.holding_service import HoldingService
    return HoldingService(db).simple_import(body.records)


@router.post("/simple-import/preview", response_model=SimpleImportPreviewResponse)
def preview_simple_import(
    body: SimpleImportPreviewRequest,
    db: Session = Depends(get_db),
):
    """只读预览快捷导入，不创建基金或持仓。"""
    from backend.services.holding_service import HoldingService
    try:
        return HoldingService(db).preview_simple_import(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/operations", response_model=list[OperationChangeResponse])
def get_operation_history(
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """读取最近统一持仓操作历史。"""
    from backend.services.holding_service import HoldingService
    return HoldingService(db).get_operation_history(limit)

"""API router - aggregates all route modules."""

from fastapi import APIRouter
from backend.api import dashboard, funds, holdings, imports, nav, analysis, advisor, scheduler, recommend, backtest, simulator, adaptive, plan, config

api_router = APIRouter(prefix="/api")

api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(funds.router, prefix="/funds", tags=["funds"])
api_router.include_router(holdings.router, prefix="/holdings", tags=["holdings"])
api_router.include_router(imports.router, prefix="/imports", tags=["imports"])
api_router.include_router(nav.router, prefix="/nav", tags=["nav"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
api_router.include_router(advisor.router, prefix="/advisor", tags=["advisor"])
api_router.include_router(backtest.router, prefix="/backtest", tags=["backtest"])
api_router.include_router(simulator.router, prefix="/simulator", tags=["simulator"])
api_router.include_router(adaptive.router, prefix="/adaptive", tags=["adaptive"])
api_router.include_router(recommend.router, prefix="/advisor/recommend", tags=["recommend"])
api_router.include_router(plan.router, prefix="/plan", tags=["plan"])
api_router.include_router(scheduler.router, prefix="/scheduler", tags=["scheduler"])
api_router.include_router(config.router, prefix="/config", tags=["config"])

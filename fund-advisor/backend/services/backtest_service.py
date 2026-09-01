"""Backtest & adaptive-learning integration layer (RFC-012).

Bridges the pure engine logic (engine/backtest.py, engine/learning.py) with the
DB, cron and report hooks:

  - record_advice(report)   : called after a report is generated -> write snapshots
  - validate_due()          : daily job -> validate pending snapshots past T+N days
  - refresh_hit_rates()     : 10-day adaptation -> recompute factor/action hit rates
  - get_stats()             : report/API -> aggregate hit rates
  - get_feedback()          : next analysis -> confidence/view calibration hints
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from backend.engine_bridge import ensure_engine_path

# 确保可以 import engine (fund-analyzer) 纯逻辑模块
ensure_engine_path()

from engine.action_mapping import normalize_action_name
from backend.models.advice_snapshot import AdviceSnapshot
from backend.models.factor_hit_rate import FactorHitRate
from backend.schemas.backtest import (
    AdviceRecord,
    FactorHitRateOut,
    BacktestStats,
    FeedbackPayload,
)

logger = logging.getLogger(__name__)

# Validation horizon (trading-ish days approximated by calendar days).
VALIDATE_AFTER_DAYS = 20


class BacktestService:
    def __init__(self, db: Session):
        self.db = db

    # ---------------- record ----------------

    def record_advice(
        self,
        report_id: int | None,
        advice_date: date,
        actions: list[dict],
        fund_navs: dict[str, Decimal],
        benchmark_at: Decimal | None = None,
        benchmark_name: str = "沪深300",
    ) -> int:
        """Write advice snapshots from a report's actions (RFC-012 §6).

        Args:
            report_id: advisor_report.id
            advice_date: the report's portfolio_date
            actions: list of {fund_code, fund_name, action, change_pct}
            fund_navs: {fund_code: nav at advice time}
            benchmark_at: benchmark index level at advice date (optional)
        """
        count = 0
        for a in actions or []:
            code = (a.get("fund_code") or "").strip()
            action = normalize_action_name(a.get("action"))
            if not code or not action:
                continue
            row = AdviceSnapshot(
                report_id=report_id,
                fund_code=code,
                fund_name=a.get("fund_name"),
                action=action,
                advice_date=advice_date,
                nav_at_advice=fund_navs.get(code),
                change_pct=a.get("change_pct"),
                benchmark_name=benchmark_name,
                benchmark_at_advice=benchmark_at,
                status="pending",
            )
            self.db.add(row)
            count += 1
        if count:
            self.db.commit()
            logger.info("record_advice: wrote %d advices for report %s", count, report_id)
        return count

    # ---------------- validate ----------------

    @staticmethod
    def _nav_before(after: date) -> date:
        return after - timedelta(days=VALIDATE_AFTER_DAYS)

    def validate_due(self) -> int:
        """Validate pending snapshots whose advice_date is >= VALIDATE_AFTER_DAYS old.

        Computes the verdict using real market data:
          - fund unit NAV at advice_date and today (from fund_nav_history)
          - benchmark (沪深300) index level at both dates (from engine market_data)
        Then persists fund_change_pct / benchmark_change_pct / verdict.
        """
        from engine.backtest import validate_advice

        due_date = date.today() - timedelta(days=VALIDATE_AFTER_DAYS)
        pending = self.db.execute(
            select(AdviceSnapshot).where(
                AdviceSnapshot.status == "pending",
                AdviceSnapshot.advice_date <= due_date,
            )
        ).scalars().all()
        if not pending:
            return 0

        # Benchmark (沪深300) closes per date -> {iso_date: close}
        benchmark_series: dict[str, float] = self._fetch_benchmark_series()

        validated = 0
        for row in pending:
            nav_before = self._nav_on(row.fund_code, row.advice_date)
            nav_after = self._nav_on(row.fund_code, date.today())
            bench_before = benchmark_series.get(row.advice_date.isoformat())
            bench_after = benchmark_series.get(date.today().isoformat())

            v = validate_advice(
                row.action,
                nav_before, nav_after,
                Decimal(str(bench_before)) if bench_before is not None else None,
                Decimal(str(bench_after)) if bench_after is not None else None,
            )
            row.status = "validated"
            row.validation_date = date.today()
            row.nav_at_validation = nav_after
            row.benchmark_at_advice = Decimal(str(bench_before)) if bench_before is not None else None
            row.benchmark_at_validation = Decimal(str(bench_after)) if bench_after is not None else None
            row.fund_change_pct = v.fund_change_pct
            row.benchmark_change_pct = v.benchmark_change_pct
            row.relative_return = v.relative_return
            row.verdict = v.verdict
            validated += 1

        self.db.commit()
        logger.info("validate_due: validated %d advices", validated)
        return validated

    @staticmethod
    def _fetch_benchmark_series() -> dict[str, float]:
        """浅300 daily closes keyed by ISO date (uses engine market_data with cache)."""
        try:
            import asyncio
            import httpx
            from engine.market_data import fetch_index_nav

            async def _run():
                async with httpx.AsyncClient(timeout=15) as client:
                    pts = await fetch_index_nav(client, "沪深300", limit=40, use_cache=True)
                return pts or []

            pts = asyncio.run(_run())
            return {d: c for d, c in pts}
        except Exception as e:  # noqa: BLE001
            logger.warning("benchmark fetch failed: %s", e)
            return {}

    def _nav_on(self, fund_code: str, d: date) -> Decimal | None:
        """Unit NAV of fund_code on or before date d."""
        from backend.models.nav_history import FundNavHistory
        row = self.db.execute(
            select(FundNavHistory)
            .where(
                FundNavHistory.fund_code == fund_code,
                FundNavHistory.nav_date <= d,
            )
            .order_by(FundNavHistory.nav_date.desc())
            .limit(1)
        ).scalar_one_or_none()
        return row.unit_nav if row else None

    # ---------------- refresh hit rates (10-day adaptation) ----------------

    def refresh_hit_rates(self, rolling_window: int = 20) -> int:
        """Recompute per factor/action hit-rates from validated advices (RFC-012 §6).

        Runs on the 10-day adaptation (and manually). factor_key is derived per-row;
        since a snapshot may carry a hint, we bucket by action type and by a simple
        factor label emitted at record time. For now we key by action type.
        """
        # We bucket primarily by action_type; factor dimension is filled from a
        # per-report 'emphasis_factor' field if present in fund_code? No — keep simple:
        # bucket by action, and also by a pseudo-factor 'all' for the overall rate.
        validated_rows = self.db.execute(
            select(AdviceSnapshot).where(AdviceSnapshot.status == "validated")
        ).scalars().all()

        buckets: dict[tuple[str, str], list[str]] = {}
        for r in validated_rows:
            key = (normalize_action_name(r.action), "action")
            buckets.setdefault(key, []).append(r.verdict or "neutral")
            # overall bucket
            buckets.setdefault(("all", "overall"), []).append(r.verdict or "neutral")

        from engine.backtest import summarize

        updated = 0
        for (factor_key, action_type), verdicts in buckets.items():
            s = summarize([type("V", (), {"verdict": v}) for v in verdicts])
            hr = s["hit_rate"]
            row = self.db.execute(
                select(FactorHitRate).where(
                    FactorHitRate.factor_key == factor_key,
                    FactorHitRate.action_type == action_type,
                )
            ).scalar_one_or_none()
            if row is None:
                row = FactorHitRate(factor_key=factor_key, action_type=action_type)
                self.db.add(row)
            row.total = s["directional"]
            row.hits = s["hits"]
            row.miss = s["miss"]
            row.hit_rate = hr
            row.rolling_window = rolling_window
            updated += 1

        self.db.commit()
        logger.info("refresh_hit_rates: updated %d buckets", updated)
        return updated

    # ---------------- feedback ----------------

    def get_feedback(self) -> FeedbackPayload:
        """Return calibrated confidence / action hit-rates for the next analysis (RFC-012 §7).

        NOTE: factor_key in factor_hit_rate currently buckets by action_type
        (reduce/increase) and an 'overall' pseudo-key — NOT by analytic view
        (trend/risk/value/tech). So the feedback we render is action-level hit rates;
        per-view emphasis stays empty until real per-view judgment data is attached.
        """
        rows = self.db.execute(select(FactorHitRate)).scalars().all()
        # Action-level hit rates: reduces/increases with real samples.
        action_hit_rates: dict[str, float] = {}
        action_samples: dict[str, int] = {}
        for r in rows:
            if r.action_type in ("action",):
                if r.hit_rate is not None:
                    action_hit_rates[r.factor_key] = float(r.hit_rate)
                action_samples[r.factor_key] = r.total or 0

        from engine.learning import build_feedback_prompt

        # No per-view data yet -> empty view_feedback, only action-level hint.
        view_feedback: dict = {}
        hint = build_feedback_prompt(view_feedback, action_hit_rates)
        return FeedbackPayload(
            view_feedback=view_feedback,
            action_hit_rates=action_hit_rates,
            prompt_hint=hint,
            has_evidence=bool(rows),
        )

    # ---------------- stats ----------------

    def get_stats(self, limit: int = 20) -> BacktestStats:
        total = self.db.execute(select(func.count()).select_from(AdviceSnapshot)).scalar() or 0
        pending = self.db.execute(
            select(func.count()).select_from(AdviceSnapshot).where(AdviceSnapshot.status == "pending")
        ).scalar() or 0
        validated_rows = self.db.execute(
            select(AdviceSnapshot).where(AdviceSnapshot.status == "validated")
        ).scalars().all()

        hits = sum(1 for r in validated_rows if r.verdict == "hit")
        miss = sum(1 for r in validated_rows if r.verdict == "miss")
        neutral = sum(1 for r in validated_rows if r.verdict == "neutral")
        directional = hits + miss
        hit_rate = Decimal(round(hits / directional, 4)) if directional else None

        by_action: dict[str, dict] = {}
        for r in validated_rows:
            action = normalize_action_name(r.action)
            d = by_action.setdefault(action, {"total": 0, "hits": 0, "miss": 0})
            d["total"] += 1
            if r.verdict == "hit":
                d["hits"] += 1
            elif r.verdict == "miss":
                d["miss"] += 1
        for d in by_action.values():
            d["directional"] = d["hits"] + d["miss"]
            d["neutral"] = d["total"] - d["directional"]
            d["coverage"] = round(d["directional"] / d["total"], 4) if d["total"] else None
            d["hit_rate"] = (
                round(d["hits"] / d["directional"], 4)
                if d["directional"] else None
            )

        factors = self.db.execute(
            select(FactorHitRate).order_by(FactorHitRate.factor_key)
        ).scalars().all()
        factor_rates = [FactorHitRateOut.model_validate(f) for f in factors]

        recent = self.db.execute(
            select(AdviceSnapshot).order_by(AdviceSnapshot.id.desc()).limit(limit)
        ).scalars().all()
        recent_records = [AdviceRecord.model_validate(r) for r in recent]

        return BacktestStats(
            total_advice=total,
            pending=pending,
            validated=len(validated_rows),
            directional=directional,
            hits=hits,
            miss=miss,
            neutral=neutral,
            hit_rate=hit_rate,
            coverage=round(directional / len(validated_rows), 4) if validated_rows else 0.0,
            by_action=by_action,
            factor_rates=factor_rates,
            recent_advice=recent_records,
        )

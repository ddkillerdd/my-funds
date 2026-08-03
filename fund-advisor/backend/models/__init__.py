"""Model registry — importing this package registers all models on Base.metadata
so `Base.metadata.create_all()` creates every table (incl. RFC-012 backtest tables).
"""

from backend.models.advice_snapshot import AdviceSnapshot  # noqa: F401
from backend.models.factor_hit_rate import FactorHitRate  # noqa: F401
from backend.models.advisor_report import AdvisorReport  # noqa: F401
from backend.models.email_send_record import EmailSendRecord  # noqa: F401
from backend.models.fund import Fund  # noqa: F401
from backend.models.holding import FundHolding  # noqa: F401
from backend.models.holding_change import HoldingChange  # noqa: F401
from backend.models.holding_daily_pnl import HoldingDailyPnL  # noqa: F401
from backend.models.import_record import ImportRecord  # noqa: F401
from backend.models.nav_history import FundNavHistory  # noqa: F401
from backend.models.portfolio_snapshot import PortfolioSnapshot  # noqa: F401
from backend.models.sim_tmp_fund import SimTmpFund  # noqa: F401
from backend.models.adaptive_proposal import AdaptiveProposal  # noqa: F401
from backend.models.strategy_override import StrategyOverride  # noqa: F401
from backend.models.fund_candidate import FundCandidate  # noqa: F401
from backend.models.portfolio_plan import PortfolioPlan  # noqa: F401
from backend.models.plan_tranche import PlanTranche  # noqa: F401
from backend.models.plan_holding import PlanHolding  # noqa: F401

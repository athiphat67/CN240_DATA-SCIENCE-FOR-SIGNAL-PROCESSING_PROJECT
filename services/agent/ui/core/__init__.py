"""
core/__init__.py
Core business logic package for Gold Trading Agent
"""

from ui.core.config import (
    PROVIDER_CHOICES,
    OPENROUTER_MODELS,
    PERIOD_CHOICES,
    INTERVAL_CHOICES,
    INTERVAL_WEIGHTS,
    AUTO_RUN_INTERVALS,
    DEFAULT_AUTO_RUN,
    SERVICE_CONFIG,
    DEFAULT_PORTFOLIO,
    UI_CONFIG,
    VALIDATION,
    THAI_MARKET_CALENDAR,
    get_interval_weight,
    validate_provider,
    validate_period,
    validate_intervals,
    get_period_label,
    get_interval_label,
    is_thailand_market_open,
)

from ui.core.services import (
    AnalysisService,
    PortfolioService,
    HistoryService,
    init_services,
)

from ui.core.renderers import (
    TraceRenderer,
    HistoryRenderer,
    PortfolioRenderer,
    StatsRenderer,
    StatusRenderer,
)

from ui.core.utils import (
    calculate_weighted_vote,
    format_voting_summary,
    format_error_message,
    format_retry_status,
    strength_indicator,
    confidence_bar,
    signal_recommendation,
    calculate_portfolio_metrics,
    validate_portfolio_update,
)



__all__ = [
    # Config
    "PROVIDER_CHOICES",
    "OPENROUTER_MODELS",
    "PERIOD_CHOICES",
    "INTERVAL_CHOICES",
    "INTERVAL_WEIGHTS",
    "AUTO_RUN_INTERVALS",
    "DEFAULT_AUTO_RUN",
    "SERVICE_CONFIG",
    "DEFAULT_PORTFOLIO",
    "UI_CONFIG",
    "VALIDATION",
    "THAI_MARKET_CALENDAR",
    "get_interval_weight",
    "validate_provider",
    "validate_period",
    "validate_intervals",
    "get_period_label",
    "get_interval_label",
    "is_thailand_market_open",
    # Services
    "AnalysisService",
    "PortfolioService",
    "HistoryService",
    "init_services",
    # Renderers
    "TraceRenderer",
    "HistoryRenderer",
    "PortfolioRenderer",
    "StatsRenderer",
    "StatusRenderer",
    # Utils
    "calculate_weighted_vote",
    "format_voting_summary",
    "format_error_message",
    "format_retry_status",
    "strength_indicator",
    "confidence_bar",
    "signal_recommendation",
    "calculate_portfolio_metrics",
    "validate_portfolio_update",
]

__version__ = "3.2"
__author__ = "Gold Trading Agent Team (athiphat-dev)"
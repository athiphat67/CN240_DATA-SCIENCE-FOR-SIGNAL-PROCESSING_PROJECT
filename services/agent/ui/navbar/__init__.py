"""
ui/navbar/__init__.py
Auto-import all pages so @navbar_page decorators register them.
"""

from .base import NavbarBuilder, AppContext, PageBase, PageComponents, navbar_page

# Import pages to trigger @navbar_page registration (order = tab order)
from . import homepage   # noqa: F401  → "🏠 Home"
from . import analysis_page  # noqa: F401  → "📊 Live Analysis"
from . import chart_page     # noqa: F401  → "📈 Live Chart"
from . import history_page   # noqa: F401  → "📜 Run History"
from . import portfolio_page # noqa: F401  → "💼 Portfolio"
from .logs_page import LogsPage

__all__ = [
    "NavbarBuilder",
    "AppContext",
    "PageBase",
    "PageComponents",
    "navbar_page",
]
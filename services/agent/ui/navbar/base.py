"""
ui/navbar/base.py
Decorator pattern for navbar page registration.

Usage:
    @navbar_page("📊 Live Analysis")
    class AnalysisPage(PageBase):
        def build(self, ctx: AppContext) -> PageComponents: ...
        def wire(self, demo, ctx): ...
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
import gradio as gr


# ─────────────────────────────────────────────
# AppContext — shared resources passed to every page
# ─────────────────────────────────────────────

@dataclass
class AppContext:
    """
    Dependency container passed to each page.
    Pages must NOT store this directly — only use it inside build() / wire().
    """
    services: Dict[str, Any]
    orchestrator: Any
    db: Any


# ─────────────────────────────────────────────
# PageComponents — what a page builds
# ─────────────────────────────────────────────

@dataclass
class PageComponents:
    """
    Holds all Gradio components a page creates.
    Passed to wire() so event wiring can reference them.
    """
    components: Dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        try:
            return self.components[name]
        except KeyError:
            raise AttributeError(f"PageComponents has no component '{name}'")

    def register(self, name: str, component: Any) -> Any:
        """Register a component by name and return it (for inline use)."""
        self.components[name] = component
        return component


# ─────────────────────────────────────────────
# PageBase — abstract base for all pages
# ─────────────────────────────────────────────

class PageBase(ABC):
    """
    Abstract base class for all navbar pages.

    Subclasses implement:
        build(ctx)  → defines Gradio components inside the tab
        wire(demo, ctx, pc)  → wires events (clicks, timers, load hooks)
    """

    #: Set by @navbar_page decorator
    label: str = ""
    _registry: List["PageBase"] = []

    @abstractmethod
    def build(self, ctx: AppContext) -> PageComponents:
        """
        Called inside `with gr.TabItem(self.label):` context.
        Must return a PageComponents with all created components.
        """
        ...

    def wire(self, demo: gr.Blocks, ctx: AppContext, pc: PageComponents) -> None:
        """
        Called AFTER all tabs are built, outside the with-block.
        Override to add .click(), .change(), .tick(), demo.load() hooks.
        """
        pass


# ─────────────────────────────────────────────
# @navbar_page decorator
# ─────────────────────────────────────────────

_PAGE_REGISTRY: List[tuple[str, PageBase]] = []


def navbar_page(label: str) -> Callable:
    """
    Class decorator that:
    1. Sets .label on the class
    2. Instantiates the class
    3. Registers it in global page order

    Example:
        @navbar_page("📊 Live Analysis")
        class AnalysisPage(PageBase): ...
    """
    def decorator(cls: type) -> type:
        cls.label = label
        instance = cls()
        _PAGE_REGISTRY.append((label, instance))
        return cls

    return decorator


# ─────────────────────────────────────────────
# NavbarBuilder — assembles all registered pages
# ─────────────────────────────────────────────

class NavbarBuilder:
    """
    Builds the full navbar (gr.Tabs) from registered pages.

    Usage in dashboard.py:
        from ui.navbar import NavbarBuilder
        ctx = AppContext(services=..., orchestrator=..., db=...)
        NavbarBuilder.build_all(demo, ctx)
    """

    @staticmethod
    def build_all(demo: gr.Blocks, ctx: AppContext) -> None:
        """
        Iterate all @navbar_page-decorated classes in registration order.
        Build each tab, then wire all events.
        """
        wiring_queue: List[tuple[PageBase, PageComponents]] = []

        with gr.Tabs():
            for label, page in _PAGE_REGISTRY:
                with gr.TabItem(label):
                    pc = page.build(ctx)
                wiring_queue.append((page, pc))

        # Wire events after all tabs exist (avoids forward-reference issues)
        for page, pc in wiring_queue:
            page.wire(demo, ctx, pc)
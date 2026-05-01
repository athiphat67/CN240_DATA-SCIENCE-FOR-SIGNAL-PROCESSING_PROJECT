# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**นักขุดทอง** — A ReAct-based AI agent for gold trading signal generation (BUY/SELL/HOLD), built for the Aom NOW platform with ฿1,500 fixed capital and ฿1,400 position size. Course project for CN240 Data Science for Signal Processing, Thammasat University.

All source code lives under `Src/`. The comprehensive architecture document is at `Src/about_src.md`.

Key capabilities added since initial release:
- **FastAPI REST layer** (`api/`) — exposes analysis, portfolio, and chart endpoints alongside the Gradio UI
- **Real-time WebSocket interceptor** (`data_engine/gold_interceptor_lite.py`) — live HSH965 + Intergold gold price feed with auto-reconnect, managed by `data_engine/tools/interceptor_manager.py`
- **Modular LLM tool registry** (`data_engine/tools/tool_registry.py`) — unified registry of all callable tools available to the ReAct agent
- **Tool result quality scoring** (`data_engine/tools/tool_result_scorer.py`) — scores each ToolResult before it enters LLM context; issues `should_proceed` / `hard_block` / `recommendations`
- **Analysis tools sub-layer** (`data_engine/analysis_tools/`) — technical pattern detection (swing low/high, divergence) and fundamental news wrappers
- **Telegram notifications** (`notification/telegram_notifier.py`) — parallel to existing Discord webhook
- **Structured logging** (`logs/`) — `sys_logger` + LLM-trace log + external trade-log API
- **Multi-page Gradio UI** (`ui/navbar/`) — tabbed navbar pages: Home, Analysis, Chart, Portfolio, History, Logs
- **Feature extraction pipeline** (`data_engine/extract_features.py`) — JSON → ML-ready CSV with time features and session labels
- **Expanded backtest data pipeline** (`backtest/data/`, `backtest/engine/market_state_builder.py`, `backtest/engine/news_provider.py`) — real HSH965 tick data, premium calculation, modular CSV loader
- **WatcherEngine** (`engine/engine.py`) — event-driven market watcher; triggers AI analysis on RSI signal with cooldown, trailing-stop management, and atomic emergency sell
- **SessionGate** (`agent_core/core/session_gate.py`) — resolves session window (night/morning/noon/evening/weekend) and attaches context (Edge vs Quota mode, confidence hint) to `market_state` before LLM call
- **React/TypeScript frontend** (`frontend/`) — Vite + Tailwind web UI (Nakkhutthong brand) with dedicated `frontend/api/main.py` FastAPI backend connecting to PostgreSQL

## Setup

```bash
pip install -r requirements.txt
cp Src/.env.example Src/.env  # fill in API keys
```

Required env vars (in `Src/.env`): Gemini API key, Groq API key, PostgreSQL connection, TwelveData API key, GoldAPI key (for live chart), optional Telegram bot token.

## Common Commands

All commands run from `Src/`:

```bash
# Web dashboard (Gradio UI on http://0.0.0.0:10000)
python ui/dashboard.py

# FastAPI REST server (uvicorn)
uvicorn api.main:app --host 0.0.0.0 --port 8000

# One-shot CLI analysis
python main.py --provider gemini --skip-fetch

# Backtest
python backtest/run_main_backtest.py --provider gemini --timeframe 1h --days 30

# Feature extraction (JSON → CSV for ML)
python data_engine/extract_features.py
```

### Testing

```bash
cd Src

# Default run (excludes llm and slow tests — use every commit)
pytest

# Run specific test categories
pytest -m unit
pytest -m integration
pytest -m data_engine
pytest -m llm          # requires real API keys
pytest -m slow

# Run a single test file or test
pytest tests/test_unit/test_portfolio.py
pytest tests/test_unit/test_portfolio.py::test_buy_order

# Dry run (collect only, no execution)
pytest --co

# With HTML report
pytest --html=test_reports/report.html
```

**Test markers** (defined in `pyproject.toml`): `unit`, `data_engine`, `llm`, `integration`, `slow`, `smoke`, `api`, `eval`.

Test files live in `tests/` with subdirectories: `test_unit/`, `test_integration/`, `test_data_engine/`, `test_llm/`, `test_llm_with_api/`.

## Architecture

The system has five layers, with strict separation — UI and API contain zero business logic.

```
ui/dashboard.py (Gradio — multi-page navbar)       api/main.py (FastAPI REST)
    → ui/navbar/  (homepage, analysis, chart, portfolio, history, logs pages)
    → ui/core/services.py (AnalysisService, PortfolioService, HistoryService)
    → ui/core/chart_service.py (real-time gold price via goldapi.io)
    → ui/core/utils.py (calculate_weighted_vote)
        → agent_core/  (ReAct loop, LLM clients, risk manager, session_gate)
        → data_engine/ (orchestrator, interceptor, tools, analysis_tools)
        → database/    (PostgreSQL: runs, llm_logs, portfolio_snapshots)
        → notification/ (Discord webhook + Telegram)
        → logs/        (sys_logger, LLM trace, external trade-log API)

engine/engine.py (WatcherEngine — event-driven trigger loop)
    → ui/core/services.py (AnalysisService)
    → data_engine/orchestrator.py (market snapshot)

frontend/  (React/TypeScript web UI — Vite + Tailwind)
    → frontend/api/main.py (Nakkhutthong FastAPI — serves /api/latest-signal etc.)
    → database/ (PostgreSQL — same DB as Gradio/REST layer)
```

### Data Flow (per analysis run)

1. **Data Collection** — `GoldTradingOrchestrator` fetches spot price (USD), USD/THB forex, Thai gold price (baht), OHLCV for 8 timeframes, and news with FinBERT sentiment. Live HSH price is optionally streamed via `gold_interceptor_lite.py` WebSocket.
2. **LLM Analysis** — For each of 8 timeframes, `ReactOrchestrator` runs a ReAct loop: attach `session_gate` context via `SessionGate` → build prompt from `roles.json` → call LLM via `LLMClientFactory` → invoke tools from `tool_registry` → score results via `ToolResultScorer` → parse JSON → validate via `RiskManager`
3. **Weighted Voting** — Aggregate decisions with weights (4h=0.30, 1h=0.22 are dominant; see `ui/core/config.py`)
4. **Persistence** — Save to PostgreSQL + send Discord/Telegram notification + optional external trade-log API
5. **UI Render** — Format trace as HTML via `ui/core/renderers.py`; Live chart rendered via TradingView widget in `ui/core/chart_renderer.py`

### Key Modules

| Module | Purpose |
|--------|---------|
| `agent_core/core/react.py` | ReactOrchestrator — main ReAct loop |
| `agent_core/core/prompt.py` | PromptBuilder, RoleRegistry, SkillRegistry |
| `agent_core/core/risk.py` | RiskManager — validates TP/SL/position sizing |
| `agent_core/core/session_gate.py` | SessionGate — resolves session window (Edge/Quota mode) and attaches context to market_state |
| `agent_core/llm/client.py` | LLMClientFactory — 8+ providers with fallback |
| `agent_core/config/roles.json` | System prompt + all trading rules (TP/SL/BUY conditions) |
| `agent_core/config/skills.json` | Skill definitions for SkillRegistry |
| `data_engine/orchestrator.py` | GoldTradingOrchestrator — coordinates live data collection |
| `data_engine/gold_interceptor_lite.py` | WebSocket interceptor for real-time HSH965 + Intergold price feed |
| `data_engine/thailand_timestamp.py` | Thai timezone utilities (get_thai_time, convert_index_to_thai_tz) |
| `data_engine/extract_features.py` | Feature extraction from orchestrator JSON → ML-ready CSV |
| `data_engine/tools/tool_registry.py` | Unified LLM tool registry (fetch_price, fetch_indicators, fetch_news, analysis tools) |
| `data_engine/tools/tool_result_scorer.py` | ToolResultScorer — scores each ToolResult (0–1); returns `ScoreReport` with `should_proceed`, `hard_block`, `recommendations` |
| `data_engine/tools/interceptor_manager.py` | Background thread manager for WebSocket interceptor |
| `data_engine/tools/schema_validator.py` | Market state schema validation |
| `data_engine/analysis_tools/technical_tools.py` | Technical pattern detection (swing low/high, divergence) |
| `data_engine/analysis_tools/fundamental_tools.py` | Fundamental/news analysis wrappers |
| `api/main.py` | FastAPI REST API — analysis, portfolio, chart, history endpoints |
| `logs/logger_setup.py` | Centralised `sys_logger` and LLM-trace logger setup |
| `logs/api_logger.py` | External trade-log API client (GoldTrade Logs API) |
| `notification/discord_notifier.py` | Discord webhook notifications |
| `notification/telegram_notifier.py` | Telegram bot notifications (BUY/SELL/HOLD signals) |
| `ui/dashboard.py` | Gradio entry point — assembles navbar pages |
| `ui/navbar/homepage.py` | Home page — signal + live price + portfolio overview card grid |
| `ui/navbar/analysis_page.py` | Analysis page — run controls, ReAct trace, LLM call logs |
| `ui/navbar/chart_page.py` | Chart page — TradingView widget + cached gold price |
| `ui/navbar/portfolio_page.py` | Portfolio page — cash/position/P&L display |
| `ui/navbar/history_page.py` | History page — past runs table |
| `ui/navbar/logs_page.py` | Logs page — LLM trace structured cards + system log (auto-refresh every 15s) |
| `ui/navbar/base.py` | PageBase abstract class + AppContext pattern for navbar page registration |
| `ui/core/chart_renderer.py` | TradingView chart HTML renderer |
| `ui/core/chart_service.py` | Real-time gold price service via goldapi.io |
| `ui/core/renderers.py` | TraceRenderer, HistoryRenderer, StatsRenderer, StatusRenderer |
| `ui/core/dashboard_css.py` | Global CSS override for Gradio (Purple × Gold design system) |
| `ui/core/utils.py` | Weighted voting helpers (calculate_weighted_vote) |
| `engine/engine.py` | WatcherEngine — event-driven RSI-triggered AI loop with trailing stop, hard SL, and atomic emergency sell |
| `frontend/api/main.py` | Nakkhutthong FastAPI — serves React frontend with `/api/latest-signal` and other endpoints |
| `backtest/engine/csv_orchestrator.py` | Drop-in CSV orchestrator for backtesting |
| `backtest/engine/market_state_builder.py` | Builds market-state JSON for each backtest candle |
| `backtest/engine/news_provider.py` | Abstract + CSV-backed news provider for backtest |
| `backtest/engine/portfolio.py` | SimPortfolio — trade simulation |
| `backtest/engine/session_manager.py` | TradingSessionManager — enforces dead-zone rules |
| `backtest/data/csv_loader.py` | Modular CSV loader with indicator computation (RSI, EMA, MACD, BB, ATR) |
| `backtest/metrics/calculator.py` | Performance metrics calculator |
| `backtest/metrics/deploy_gate.py` | 7-check PASS/FAIL deployment gate |
| `backtest/run_main_backtest.py` | Backtest entry point |

### Backtest Data Structure

```
backtest/data/
    csv_loader.py                  ← main loader (indicators computed here)
    latest_data/                   ← Final_Merged_HSH_M5.csv (production input)
    merge_data/                    ← merge scripts + Cleaned/Final CSVs
    HSH965_BuySell_Clean/          ← raw HSH965 tick data + cleaning scripts
    HSH965_Mock/                   ← mock OHLC data for offline testing
    premium_hsh/                   ← HSH premium calculation vs spot price
    news_data/                     ← gold_macro_news_v1.csv (static news for backtest)
```

### LLM Provider Fallback

Configured in `ui/core/config.py`. Example: `"gemini" → ["gemini", "groq", "mock"]`. Always falls back to `mock` if all real providers fail.

### Trading Rules (in `roles.json`)

These are hardcoded rules injected into the LLM system prompt — not learned behavior:
- **Position size:** Always ฿1,400 (Aom NOW minimum)
- **Dead zone:** No trading 02:00–06:14 Bangkok time
- **BUY:** Requires cash ≥ ฿1,408, not holding, and ≥2 of 3 bullish signals (RSI 40–60, MACD > 0, Price > EMA20), confidence ≥ 0.75
- **TP triggers (SELL when any):** PnL ≥ +฿300; or PnL ≥ +฿150 AND RSI > 65; or PnL ≥ +฿100 AND MACD hist < 0
- **SL triggers (SELL when any):** PnL ≤ -฿150; or PnL ≤ -฿80 AND RSI < 35; or force-close 01:30–01:59 if holding
- **Session windows (weekday):** night 00:00–01:59, morning 06:15–11:59, noon 12:00–17:59, evening 18:00–23:59; weekend 09:30–17:30
- **WatcherEngine hard rules:** trailing SL locks in profit at cost + ฿5/g once profit ≥ ฿20/g; hard stop loss at ฿15/g loss

### React/TypeScript Frontend

A separate web frontend lives under `frontend/` — it is independent of the Gradio UI:

```
frontend/
    api/main.py            ← Nakkhutthong FastAPI (psycopg2 → PostgreSQL)
    pages/index.tsx        ← main page (overview + signal log)
    components/
        Navbar.tsx
        overview/          ← GrossPnL, SignalDetail, SignalBreakdown, StatsStack, etc.
        sections/          ← HeroSection, HowItWorksStepsSection, etc.
    styles/tailwind.css
    vite.config.ts
```

The `frontend/api/main.py` FastAPI serves endpoints (e.g. `/api/latest-signal`) to the React UI and reads from the same PostgreSQL database used by the Gradio layer. It is separate from `api/main.py` (the analysis/portfolio REST API).

### Data Engine Pipeline Documentation

`data_engine/pipeline_flow/` contains architecture notes only (no runnable code):
- `about_data_engine.md` — data engine overview
- `data_engine_output_flow_v1.md` — output flow diagram
- `data_engine_fix.md` — known issues and fixes log

### Backtest vs Production

`CSVOrchestrator` is a drop-in replacement for `GoldTradingOrchestrator` — backtest uses the exact same `ReactOrchestrator` pipeline, just fed from CSV rows instead of live API calls. `MarketStateBuilder` constructs the market-state JSON per candle. `NewsProvider` (abstract) supplies static CSV news matched by timestamp. `TradingSessionManager` enforces session compliance during backtest.


 

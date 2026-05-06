-- ============================================================
-- HSH ML Trader — Supabase DDL Schema
-- Phase 8 · PostgreSQL (Supabase)
-- ============================================================

-- ─── Table 1: signals ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signals (
    id              TEXT PRIMARY KEY,
    bar_time        TIMESTAMPTZ NOT NULL,
    session         TEXT NOT NULL,
    signal_type     TEXT NOT NULL DEFAULT 'BUY',
    ranker_score    NUMERIC(10,6) NOT NULL,
    passed          BOOLEAN NOT NULL,
    reject_reason   TEXT,
    dry_run         BOOLEAN NOT NULL DEFAULT false,
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_bar_time ON signals(bar_time DESC);
CREATE INDEX IF NOT EXISTS idx_signals_passed   ON signals(passed) WHERE passed = true;


-- ─── Table 2: positions ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS positions (
    id                  TEXT PRIMARY KEY,
    signal_id           TEXT REFERENCES signals(id),
    status              TEXT NOT NULL DEFAULT 'OPEN',

    entry_ask_price     NUMERIC(10,2) NOT NULL,
    entry_bid_price     NUMERIC(10,2) NOT NULL,
    hsh_spread          NUMERIC(10,2) NOT NULL,
    entry_time          TIMESTAMPTZ NOT NULL,
    investment_thb      NUMERIC(12,2) NOT NULL,
    gold_weight         NUMERIC(12,5) NOT NULL,
    actual_cost_thb     NUMERIC(12,4) NOT NULL,
    spread_cost_thb     NUMERIC(12,4) NOT NULL,
    breakeven_bid       NUMERIC(10,2) NOT NULL,

    atr_used            NUMERIC(10,2),
    tp_bid_price        NUMERIC(10,2),
    sl_bid_price        NUMERIC(10,2),
    tp_distance_thb     NUMERIC(10,2),
    sl_distance_thb     NUMERIC(10,2),
    tp_pnl_thb          NUMERIC(12,4),
    sl_pnl_thb          NUMERIC(12,4),
    risk_reward_ratio   NUMERIC(6,2),

    close_bid_price     NUMERIC(10,2),
    close_at            TIMESTAMPTZ,
    close_reason        TEXT,
    realized_pnl_thb    NUMERIC(12,4),
    pnl_pct             NUMERIC(8,4),

    dry_run             BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_positions_status     ON positions(status) WHERE status = 'OPEN';
CREATE INDEX IF NOT EXISTS idx_positions_entry_time ON positions(entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_positions_signal_id  ON positions(signal_id);


-- ─── Table 3: bar_logs ────────────────────────────────────────────────────────
-- Regular table (no partitioning) — M10 x 90 days = ~4,200 rows max
-- Retention: DELETE FROM bar_logs WHERE created_at < NOW() - INTERVAL '90 days';

CREATE TABLE IF NOT EXISTS bar_logs (
    id              BIGSERIAL PRIMARY KEY,
    bar_time        TIMESTAMPTZ NOT NULL UNIQUE,
    session         TEXT,
    ranker_score    NUMERIC(10,6),
    signal_passed   BOOLEAN,
    hsh_close_ask   NUMERIC(10,2),
    hsh_close_bid   NUMERIC(10,2),
    atr_48          NUMERIC(10,2),
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bar_logs_bar_time ON bar_logs(bar_time DESC);
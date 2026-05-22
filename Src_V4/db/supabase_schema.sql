-- ─── Table 1: system_state ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS v3_system_state ( 
    id                  INT PRIMARY KEY DEFAULT 1,
    current_position    TEXT NOT NULL DEFAULT 'EMPTY',  -- 'EMPTY' | 'HOLDING'
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    note                TEXT
);
INSERT INTO v3_system_state (id, current_position) VALUES (1, 'EMPTY') ON CONFLICT (id) DO NOTHING;

-- ─── Table 2: signals ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS v3_signals (
    id              TEXT PRIMARY KEY,          -- "sig_YYYYMMDD_HHMMSS"
    bar_time        TIMESTAMPTZ NOT NULL,
    session         TEXT NOT NULL,
    signal_type     TEXT NOT NULL,             -- 'BUY' | 'SELL' | 'HOLD'
    ranker_score    NUMERIC(10,6) NOT NULL,
    state_before    TEXT NOT NULL,
    hsh_ask_price   NUMERIC(10,2),
    hsh_bid_price   NUMERIC(10,2),
    xau_price       NUMERIC(10,4),
    atr_at_signal   NUMERIC(10,2),
    passed          BOOLEAN NOT NULL,
    reject_reason   TEXT,
    dry_run         BOOLEAN NOT NULL DEFAULT false,
    features_snap   JSONB,
    rationale_text  TEXT,
    top_shap_features JSONB,
    execution_status TEXT DEFAULT 'SIGNAL_ONLY',
    confirmed_at    TIMESTAMPTZ,
    confirmed_price NUMERIC(10,2),
    confirm_note    TEXT,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_bar_time ON v3_signals(bar_time DESC);
CREATE INDEX IF NOT EXISTS idx_signals_type ON v3_signals(signal_type) WHERE passed = true;

-- ─── Table 3: active trades ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS v3_active_trades (
    id                  BIGSERIAL PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'OPEN', -- OPEN | CLOSED | CANCELLED
    entry_signal_id     TEXT REFERENCES v3_signals(id),
    entry_time          TIMESTAMPTZ DEFAULT NOW(),
    entry_bar_time      TIMESTAMPTZ,
    entry_ask           NUMERIC(10,2) NOT NULL,
    entry_bid_at_signal NUMERIC(10,2),
    entry_score         NUMERIC(10,6),
    entry_note          TEXT,
    exit_signal_id      TEXT REFERENCES v3_signals(id),
    exit_time           TIMESTAMPTZ,
    exit_bid            NUMERIC(10,2),
    exit_score          NUMERIC(10,6),
    exit_reason         TEXT,
    exit_note           TEXT,
    pnl_thb             NUMERIC(10,2),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_active_trades_status ON v3_active_trades(status);
CREATE INDEX IF NOT EXISTS idx_active_trades_entry_signal ON v3_active_trades(entry_signal_id);
CREATE INDEX IF NOT EXISTS idx_active_trades_exit_signal
ON public.v3_active_trades(exit_signal_id);

-- ─── Table 4: bar_logs (Debug & Retrain) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS v3_bar_logs (
    id              BIGSERIAL PRIMARY KEY,
    bar_time        TIMESTAMPTZ NOT NULL UNIQUE,
    session         TEXT,
    state_at_bar    TEXT,
    ranker_score    NUMERIC(10,6),
    signal_passed   BOOLEAN,
    signal_type     TEXT,
    hsh_close_ask   NUMERIC(10,2),
    hsh_close_bid   NUMERIC(10,2),
    atr_48          NUMERIC(10,2),
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bar_logs_bar_time ON v3_bar_logs(bar_time DESC);

ALTER TABLE public.v3_signals
ADD COLUMN IF NOT EXISTS rationale_text TEXT,
ADD COLUMN IF NOT EXISTS top_shap_features JSONB,
ADD COLUMN IF NOT EXISTS execution_status TEXT DEFAULT 'SIGNAL_ONLY',
ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS confirmed_price NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS confirm_note TEXT,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Optional but strongly recommended:
-- enforce only one OPEN trade at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_one_open_trade
ON public.v3_active_trades (status)
WHERE status = 'OPEN';

-- Helpful indexes for execution flow.
CREATE INDEX IF NOT EXISTS idx_signals_execution_status
ON public.v3_signals(execution_status);

CREATE INDEX IF NOT EXISTS idx_signals_pending_buy
ON public.v3_signals(bar_time DESC)
WHERE signal_type = 'BUY'
  AND passed = true
  AND execution_status IN ('PENDING_CONFIRM', 'SIGNAL_ONLY');

-- ─── Table 5: pipeline monitor ─────────────────────────────────────────────
-- Mirror of the DDL block at the top of monitoring/pipeline_monitor.py.
-- Upserted on conflict (bar_time) by pipeline_monitor.save_to_db().
CREATE TABLE IF NOT EXISTS v3_data_pipeline (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bar_time         TEXT NOT NULL UNIQUE,
    run_at           TIMESTAMPTZ DEFAULT NOW(),
    session          TEXT,
    pipeline_status  TEXT,
    total_ms         INT,

    l1_status        TEXT,
    l1_ms            INT,
    l1_bars          INT,
    l1_hsh_ask       NUMERIC,
    l1_hsh_bid       NUMERIC,
    l1_xau_close     NUMERIC,
    l1_usd_close     NUMERIC,
    l1_error         TEXT,

    l2_status        TEXT,
    l2_ms            INT,
    l2_atr_48        NUMERIC,
    l2_rsi_14        NUMERIC,
    l2_rsi_6         NUMERIC,
    l2_bb_pos        NUMERIC,
    l2_srvr          NUMERIC,
    l2_regime        INT,
    l2_spread_norm   NUMERIC,
    l2_features      JSONB,
    l2_error         TEXT,

    l3_status        TEXT,
    l3_ms            INT,
    l3_score         NUMERIC,
    l3_model         TEXT,
    l3_top_shap_feat TEXT,
    l3_top_shap_val  NUMERIC,
    l3_error         TEXT,

    l4_status        TEXT,
    l4_ms            INT,
    l4_state_before  TEXT,
    l4_signal_type   TEXT,
    l4_passed        BOOLEAN,
    l4_reject_reason TEXT,
    l4_gates         JSONB,
    l4_error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_data_pipeline_run_at ON v3_data_pipeline(run_at DESC);

-- ─── Table 6: HSH965 tick prices ───────────────────────────────────────────
-- Source of truth for HSH gold tick feed. Inserted by the price ingestor;
-- read by core/candle_builder.py via _fetch_table_chunked() with timestamp
-- range filters. INSERT-only — no on_conflict path in the writer.
CREATE TABLE IF NOT EXISTS gold_prices_hsh (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    ask_96          NUMERIC(10,2),
    bid_96          NUMERIC(10,2),
    bid_99          NUMERIC(10,2),
    ask_99          NUMERIC(10,2),
    market_status   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gold_prices_hsh_timestamp
    ON gold_prices_hsh(timestamp DESC);

-- ─── Table 7: Intergold spot + FX ticks ────────────────────────────────────
-- spot_price = XAU/USD, usd_thb = USD→THB FX. Same access pattern as
-- gold_prices_hsh.
CREATE TABLE IF NOT EXISTS gold_prices_ig (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    bid_96          NUMERIC(10,2),
    ask_96          NUMERIC(10,2),
    bid_99          NUMERIC(10,2),
    ask_99          NUMERIC(10,2),
    spot_price      NUMERIC(10,4),
    usd_thb         NUMERIC(10,4),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_gold_prices_ig_timestamp
    ON gold_prices_ig(timestamp DESC);

-- ─── Migration: add missing columns if DB already exists ───────────────────
ALTER TABLE public.gold_prices_hsh
    ADD COLUMN IF NOT EXISTS bid_99        NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS ask_99        NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS market_status TEXT;

ALTER TABLE public.gold_prices_ig
    ADD COLUMN IF NOT EXISTS bid_96 NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS ask_96 NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS bid_99 NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS ask_99 NUMERIC(10,2);

-- Reload Supabase/PostgREST schema cache.
NOTIFY pgrst, 'reload schema';
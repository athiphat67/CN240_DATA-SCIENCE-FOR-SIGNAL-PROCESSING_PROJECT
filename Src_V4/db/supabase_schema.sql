-- ─── Table 1: system_state ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS v3_system_state ( 
    id                  INT PRIMARY KEY DEFAULT 1,
    current_position    TEXT NOT NULL DEFAULT 'EMPTY',  -- 'EMPTY' | 'HOLDING'
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    note                TEXT
);
INSERT INTO system_state (id, current_position) VALUES (1, 'EMPTY') ON CONFLICT (id) DO NOTHING;

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
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_bar_time ON v3_signals(bar_time DESC);
CREATE INDEX IF NOT EXISTS idx_signals_type ON v3_signals(signal_type) WHERE passed = true;

-- ─── Table 3: bar_logs (Debug & Retrain) ───────────────────────────────────
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
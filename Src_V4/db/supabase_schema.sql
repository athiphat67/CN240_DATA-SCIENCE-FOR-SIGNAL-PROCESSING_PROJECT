-- =============================================================================
--  supabase_schema.sql  —  Gold Trading Bot v3
--  Last updated: 2026-05-08
-- =============================================================================


-- ─── Table 0a: gold_prices_hsh (Input — Raw HSH Gold Bar Prices) ──────────
CREATE TABLE IF NOT EXISTS gold_prices_hsh (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL UNIQUE,
    bid_96          NUMERIC(10, 2),            -- ราคาซื้อทอง 96.5%
    ask_96          NUMERIC(10, 2),            -- ราคาขายทอง 96.5%
    bid_99          NUMERIC(10, 2),            -- ราคาซื้อทอง 99.99%
    ask_99          NUMERIC(10, 2),            -- ราคาขายทอง 99.99%
    market_state    TEXT,                      -- เช่น 'OPEN' | 'CLOSED' | 'HOLIDAY'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_hsh_timestamp ON gold_prices_hsh(timestamp DESC);


-- ─── Table 0b: gold_prices_ig (Input — Raw IG World Market Prices) ────────
CREATE TABLE IF NOT EXISTS gold_prices_ig (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL UNIQUE,
    bid_96          NUMERIC(10, 2),            -- XAU แปลงเป็นบาท 96.5%
    ask_96          NUMERIC(10, 2),
    bid_99          NUMERIC(10, 2),            -- XAU แปลงเป็นบาท 99.99%
    ask_99          NUMERIC(10, 2),
    spot_price      NUMERIC(10, 4),            -- XAU/USD spot price
    usd_thb         NUMERIC(10, 6),            -- อัตราแลกเปลี่ยน USD/THB
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ig_timestamp ON gold_prices_ig(timestamp DESC);


-- ─── Table 1: v3_system_state ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS v3_system_state (
    id                  INT PRIMARY KEY DEFAULT 1,
    current_position    TEXT NOT NULL DEFAULT 'EMPTY',  -- 'EMPTY' | 'HOLDING'
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    note                TEXT
);
-- FIX: ชื่อตารางในคำสั่ง INSERT ต้องตรงกับ CREATE TABLE ด้านบน
INSERT INTO v3_system_state (id, current_position)
    VALUES (1, 'EMPTY')
    ON CONFLICT (id) DO NOTHING;


-- ─── Table 2: v3_signals (Output — Signal Records) ────────────────────────
CREATE TABLE IF NOT EXISTS v3_signals (
    id                  TEXT PRIMARY KEY,          -- "sig_YYYYMMDD_HHMMSS"
    bar_time            TIMESTAMPTZ NOT NULL,
    session             TEXT NOT NULL,             -- 'ASIA' | 'LONDON' | 'NY'
    signal_type         TEXT NOT NULL,             -- 'BUY' | 'SELL' | 'HOLD'
    ranker_score        NUMERIC(10, 6) NOT NULL,
    state_before        TEXT NOT NULL,             -- 'EMPTY' | 'HOLDING'

    -- ราคาอ้างอิง ณ เวลาที่เกิด Signal
    hsh_ask_price       NUMERIC(10, 2),
    hsh_bid_price       NUMERIC(10, 2),
    xau_price           NUMERIC(10, 4),
    atr_at_signal       NUMERIC(10, 2),

    -- ผลการกรอง
    passed              BOOLEAN NOT NULL,
    reject_reason       TEXT,
    dry_run             BOOLEAN NOT NULL DEFAULT FALSE,

    -- Feature Snapshot (ML Input)
    features_snap       JSONB,

    -- AI Explainability (NEW)
    rationale_text      TEXT,                      -- คำอธิบายเหตุผลจาก AI
    top_shap_features   JSONB,                     -- SHAP values { feature: value, ... }

    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_signals_bar_time ON v3_signals(bar_time DESC);
CREATE INDEX IF NOT EXISTS idx_signals_type     ON v3_signals(signal_type) WHERE passed = TRUE;


-- ─── Table 3: v3_bar_logs (Debug & Retrain) ───────────────────────────────
CREATE TABLE IF NOT EXISTS v3_bar_logs (
    id              BIGSERIAL PRIMARY KEY,
    bar_time        TIMESTAMPTZ NOT NULL UNIQUE,
    session         TEXT,
    state_at_bar    TEXT,
    ranker_score    NUMERIC(10, 6),
    signal_passed   BOOLEAN,
    signal_type     TEXT,
    hsh_close_ask   NUMERIC(10, 2),
    hsh_close_bid   NUMERIC(10, 2),
    atr_48          NUMERIC(10, 2),
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bar_logs_bar_time ON v3_bar_logs(bar_time DESC);
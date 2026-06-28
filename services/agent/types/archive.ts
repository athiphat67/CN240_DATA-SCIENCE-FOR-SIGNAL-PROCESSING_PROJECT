// src/types/archive.ts

export interface ArchiveSummary {
  total_pnl_thb: number;
  win_rate: number;
  total_trades: number;
  growth_pct: number;
  sync_status: string;
}

export interface TradeRecord {
  id: number;
  run_id: number | null;
  action: 'BUY' | 'SELL';
  price_thb: number;
  gold_grams: number;
  pnl_thb: number | null;
  pnl_pct: number | null;
  executed_at: string;
  note: string;
  rationale: string;
  confidence: number;
}

export interface SignalRecord {
  id: number;
  run_at: string;
  signal: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  rationale: string;
  provider: string;
  trend: string;
}

export interface LogRecord {
  id: number;
  logged_at: string;
  step_type: 'THOUGHT' | 'ACTION' | 'OBSERVATION' | 'THOUGHT_FINAL';
  provider: string;
  token_total: number;
  elapsed_ms: number;
  trace_preview: string;
}
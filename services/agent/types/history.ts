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
  // Intelligence Data (จากตาราง runs)
  rationale: string;
  confidence: number;
  provider: string;
  iterations_used: number;
  tool_calls_used: number;
  // Market Snapshot Data
  rsi: number;
  macd_line: number;
  trend: string;
  gold_usd: number;
  gold_thb: number;
  is_weekend: boolean;
  data_quality: string;
}
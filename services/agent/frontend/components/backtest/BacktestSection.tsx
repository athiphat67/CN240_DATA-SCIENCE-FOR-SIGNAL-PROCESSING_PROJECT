import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  TrendingUp, Target, ShieldAlert, Activity,
  Download, ArrowUpRight, RefreshCw, AlertCircle,
  ChevronDown, ChevronRight, TrendingDown, Filter,
  CheckCircle2, XCircle, Clock, BarChart3, Minus
} from 'lucide-react';
import {
  ComposedChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts';
import { OverviewHeader } from '../overview/OverviewHeader';

// ─── Types ────────────────────────────────────────────────────────────────────
interface BacktestSummary {
  model_name:                        string;
  run_date:                          string;
  trade_net_pnl_thb:                 number;
  risk_total_return_pct:             number;
  trade_win_rate_pct:                number;
  trade_winning_trades:              number;
  trade_losing_trades:               number;
  risk_mdd_pct:                      number;
  trade_profit_factor:               number;
  trade_expectancy_thb:              number;
  risk_sharpe_ratio:                 number;
  risk_sortino_ratio:                number;
  risk_annualized_return_pct:        number;
  risk_initial_portfolio_thb:        number;
  risk_final_portfolio_thb:          number;
  trade_total_trades:                number;
  trade_gross_profit_thb:            number;
  trade_gross_loss_thb:              number;
  trade_calmar_ratio:                number;
  llm_directional_accuracy_pct:      number;
  final_directional_accuracy_pct:    number;
  session_compliance_compliance_pct: number;
  risk_candles_total:                number;
}

interface EquityPoint {
  date:       string;
  value:      number;
  signal:     string;
  pnl:        number;
  price:      number;      // ราคาทอง close_thai
  raw_ts:     string;      // ISO timestamp สำหรับ filter timeframe
  profitable: boolean;
}

interface TradeRow {
  timestamp:        string;
  signal:           'BUY' | 'SELL';
  confidence:       number;
  pnl:              number;
  position_size:    number;
  stop_loss:        number;
  take_profit:      number;
  rationale:        string;
  llm_signal:       string;
  llm_confidence:   number;
  correct:          boolean;
  profitable:       boolean;
  rejection_reason: string;
  portfolio_value:  number;
  price:            number;
}

// ─── Timeframe config ─────────────────────────────────────────────────────────
const TIMEFRAMES = [
  { key: '1W',  label: '1W',  days: 7    },
  { key: '2W',  label: '2W',  days: 14   },
  { key: '1M',  label: '1M',  days: 30   },
  { key: '3M',  label: '3M',  days: 90   },
  { key: 'ALL', label: 'ALL', days: 9999 },
] as const;
type TFKey = typeof TIMEFRAMES[number]['key'];

// ─── API base URL ─────────────────────────────────────────────────────────────
const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

// ─── Signal dot colors ────────────────────────────────────────────────────────
// BUY+profit=เขียว | BUY+loss=ส้ม | SELL+profit=ฟ้า | SELL+loss=แดง
const dotColor = (signal: string, profitable: boolean) => {
  if (signal === 'BUY')  return profitable ? '#10b981' : '#f59e0b';
  if (signal === 'SELL') return profitable ? '#06b6d4' : '#f43f5e';
  return 'transparent';
};

// ─── Custom dot: ▲ BUY / ▼ SELL บนกราฟราคาทอง ───────────────────────────────
const PriceSignalDot = (props: any) => {
  const { cx, cy, payload } = props;
  if (!cx || !cy || !payload) return null;
  const { signal, profitable } = payload;
  if (signal !== 'BUY' && signal !== 'SELL') return <g />;
  const col   = dotColor(signal, profitable);
  const isBuy = signal === 'BUY';
  return (
    <g>
      <circle cx={cx} cy={cy} r={11}  fill={col} fillOpacity={0.18} />
      <circle cx={cx} cy={cy} r={5}   fill={col} stroke="#fff" strokeWidth={2} />
      {isBuy
        ? <polygon points={`${cx},${cy - 15} ${cx - 5},${cy - 8} ${cx + 5},${cy - 8}`} fill={col} />
        : <polygon points={`${cx},${cy + 15} ${cx - 5},${cy + 8} ${cx + 5},${cy + 8}`} fill={col} />
      }
    </g>
  );
};

// ─── Smaller dot บน equity curve ─────────────────────────────────────────────
const EquitySignalDot = (props: any) => {
  const { cx, cy, payload } = props;
  if (!cx || !cy || !payload) return null;
  const { signal, profitable } = payload;
  if (signal !== 'BUY' && signal !== 'SELL') return <g />;
  const col = dotColor(signal, profitable);
  return (
    <g>
      <circle cx={cx} cy={cy} r={7}   fill={col} fillOpacity={0.15} />
      <circle cx={cx} cy={cy} r={3.5} fill={col} stroke="#fff" strokeWidth={1.5} />
    </g>
  );
};

// ─── Shared Tooltip (แสดงทั้งราคาทองและ portfolio พร้อมกัน) ──────────────────
const SharedTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as EquityPoint | undefined;
  if (!d) return null;
  const isTrade = d.signal === 'BUY' || d.signal === 'SELL';
  const col     = isTrade ? dotColor(d.signal, d.profitable) : '#94a3b8';

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/98 backdrop-blur p-4 shadow-2xl text-[12px] min-w-[210px]">
      <p className="font-bold text-slate-400 mb-2 text-[11px] tracking-wider uppercase">{label}</p>

      {d.price > 0 && (
        <div className="flex justify-between items-center mb-1">
          <span className="text-slate-500 font-medium">ราคาทอง</span>
          <span className="font-black text-amber-700">
            {d.price.toLocaleString('th-TH', { minimumFractionDigits: 2 })} ฿
          </span>
        </div>
      )}

      <div className="flex justify-between items-center mb-2">
        <span className="text-slate-500 font-medium">Portfolio</span>
        <span className="font-black text-purple-700">
          {d.value.toLocaleString('th-TH', { minimumFractionDigits: 2 })} ฿
        </span>
      </div>

      {isTrade && (
        <div className="pt-2 border-t border-slate-100">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-black"
              style={{ backgroundColor: `${col}22`, color: col }}>
              {d.signal === 'BUY' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              {d.signal}
            </span>
            <span className={`font-black text-[13px] ${d.pnl > 0 ? 'text-emerald-600' : d.pnl < 0 ? 'text-rose-500' : 'text-slate-400'}`}>
              {d.pnl > 0 ? '+' : ''}{d.pnl.toFixed(2)} ฿
            </span>
          </div>
          <p className="mt-1 text-[10px] font-bold" style={{ color: col }}>
            {d.profitable ? '✓ Profitable' : '✗ Loss'}
          </p>
        </div>
      )}
    </div>
  );
};

// ─── Trade History Row ────────────────────────────────────────────────────────
const TradeHistoryRow = ({ trade, index }: { trade: TradeRow; index: number }) => {
  const [expanded, setExpanded] = useState(false);
  const isBuy    = trade.signal === 'BUY';
  const isProfit = trade.pnl > 0;

  return (
    <>
      <tr
        className={`border-b border-slate-100 cursor-pointer transition-colors duration-150 ${
          expanded ? 'bg-purple-50/70' : 'hover:bg-slate-50/80'
        }`}
        onClick={() => setExpanded(e => !e)}
      >
        <td className="py-3 pl-5 pr-2 text-[11px] font-mono text-slate-400 w-10">{index + 1}</td>
        <td className="py-3 px-3">
          <span className="text-[12px] font-mono text-slate-600 whitespace-nowrap">{trade.timestamp}</span>
        </td>
        <td className="py-3 px-3">
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-black ${
            isBuy ? 'bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200'
                  : 'bg-rose-100 text-rose-600 ring-1 ring-rose-200'
          }`}>
            {isBuy ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {trade.signal}
          </span>
        </td>
        <td className="py-3 px-3">
          <div className="flex items-center gap-2">
            <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full bg-gradient-to-r from-purple-400 to-fuchsia-500"
                style={{ width: `${Math.min(trade.confidence * 100, 100)}%` }} />
            </div>
            <span className="text-[12px] font-bold text-slate-600">{(trade.confidence * 100).toFixed(0)}%</span>
          </div>
        </td>
        <td className="py-3 px-3 text-[12px] font-mono text-slate-600">
          {trade.price > 0 ? trade.price.toLocaleString('th-TH') : '—'}
        </td>
        <td className="py-3 px-3">
          <span className={`text-[13px] font-black ${isProfit ? 'text-emerald-600' : trade.pnl < 0 ? 'text-rose-500' : 'text-slate-400'}`}>
            {trade.pnl > 0 ? '+' : ''}{trade.pnl.toFixed(2)} ฿
          </span>
        </td>
        <td className="py-3 px-3">
          {trade.profitable
            ? <CheckCircle2 size={15} className="text-emerald-500" />
            : trade.pnl < 0
            ? <XCircle size={15} className="text-rose-400" />
            : <Minus size={15} className="text-slate-300" />}
        </td>
        <td className="py-3 pr-4 pl-2 text-right">
          {expanded
            ? <ChevronDown size={14} className="text-purple-400 ml-auto" />
            : <ChevronRight size={14} className="text-slate-300 ml-auto" />}
        </td>
      </tr>

      {expanded && (
        <tr className="bg-purple-50/50">
          <td colSpan={8} className="px-6 py-4">
            <div className="grid grid-cols-12 gap-4">
              <div className="col-span-12 md:col-span-7">
                <p className="text-[10px] font-black text-purple-400 uppercase tracking-widest mb-2 flex items-center gap-1.5">
                  <BarChart3 size={10} /> LLM Rationale
                </p>
                <p className="text-[13px] text-slate-700 leading-relaxed font-medium bg-white/80 rounded-xl p-3 border border-purple-100">
                  {trade.rationale && trade.rationale !== '—'
                    ? trade.rationale
                    : <span className="text-slate-400 italic">ไม่มีข้อมูลเหตุผล</span>}
                </p>
              </div>
              <div className="col-span-12 md:col-span-5 grid grid-cols-2 gap-3">
                <div className="bg-white/80 rounded-xl p-3 border border-purple-100">
                  <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1">Position Size</p>
                  <p className="text-[14px] font-black text-slate-800">
                    {trade.position_size > 0 ? `${trade.position_size.toLocaleString('th-TH')} ฿` : '—'}
                  </p>
                </div>
                <div className="bg-white/80 rounded-xl p-3 border border-purple-100">
                  <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1">Portfolio</p>
                  <p className="text-[14px] font-black text-slate-800">
                    {trade.portfolio_value > 0 ? `${trade.portfolio_value.toLocaleString('th-TH')} ฿` : '—'}
                  </p>
                </div>
                <div className="bg-white/80 rounded-xl p-3 border border-emerald-100">
                  <p className="text-[10px] font-black text-emerald-400 uppercase tracking-widest mb-1">Take Profit</p>
                  <p className="text-[14px] font-black text-emerald-700">
                    {trade.take_profit > 0 ? trade.take_profit.toLocaleString('th-TH') : '—'}
                  </p>
                </div>
                <div className="bg-white/80 rounded-xl p-3 border border-rose-100">
                  <p className="text-[10px] font-black text-rose-400 uppercase tracking-widest mb-1">Stop Loss</p>
                  <p className="text-[14px] font-black text-rose-600">
                    {trade.stop_loss > 0 ? trade.stop_loss.toLocaleString('th-TH') : '—'}
                  </p>
                </div>
                {trade.llm_signal !== trade.signal && (
                  <div className="col-span-2 bg-amber-50/80 rounded-xl p-3 border border-amber-100">
                    <p className="text-[10px] font-black text-amber-500 uppercase tracking-widest mb-1">⚡ Risk Override</p>
                    <p className="text-[12px] text-amber-700 font-medium">
                      LLM: <span className="font-black">{trade.llm_signal}</span> ({(trade.llm_confidence * 100).toFixed(0)}%)
                      {trade.rejection_reason && <> → <span className="italic">{trade.rejection_reason}</span></>}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};

// ─── Main Component ────────────────────────────────────────────────────────────
export const BacktestSection = () => {
  const [summary,     setSummary]     = useState<BacktestSummary | null>(null);
  const [equityCurve, setEquityCurve] = useState<EquityPoint[]>([]);
  const [trades,      setTrades]      = useState<TradeRow[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState<string | null>(null);
  const [lastFetch,   setLastFetch]   = useState<Date | null>(null);

  const [activeTimeframe, setActiveTimeframe] = useState<TFKey>('ALL');
  const [signalFilter,    setSignalFilter]    = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const [tradeSearch,     setTradeSearch]     = useState('');
  const [page,            setPage]            = useState(1);
  const PAGE_SIZE = 20;

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryRes, curveRes, tradesRes] = await Promise.all([
        fetch(`${API_BASE}/api/backtest/summary`),
        fetch(`${API_BASE}/api/backtest/equity-curve?limit=2000`),
        fetch(`${API_BASE}/api/backtest/trades?limit=500`),
      ]);
      if (!summaryRes.ok) throw new Error(`Summary API error: ${summaryRes.status}`);
      if (!curveRes.ok)   throw new Error(`Equity curve API error: ${curveRes.status}`);

      const [summaryData, curveData, tradesData] = await Promise.all([
        summaryRes.json(),
        curveRes.json(),
        tradesRes.ok ? tradesRes.json() : Promise.resolve([]),
      ]);
      setSummary(summaryData);
      setEquityCurve(curveData);
      setTrades(tradesData);
      setLastFetch(new Date());
    } catch (err: any) {
      setError(err.message ?? 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  // ─── Filter by timeframe ──────────────────────────────────────────────────
  const filteredCurve = useMemo(() => {
    if (!equityCurve.length || activeTimeframe === 'ALL') return equityCurve;

    const tf     = TIMEFRAMES.find(t => t.key === activeTimeframe)!;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - tf.days);

    // ถ้า raw_ts มีค่า → filter จาก date จริง
    if (equityCurve[0]?.raw_ts) {
      const filtered = equityCurve.filter(p => {
        try { return new Date(p.raw_ts) >= cutoff; } catch { return true; }
      });
      // fallback: ถ้า filter ได้น้อยเกินไป ให้ใช้ slice แทน
      if (filtered.length > 10) return filtered;
    }
    // Fallback: 30m candles = 48 จุด/วัน
    const keep = tf.days * 48;
    return equityCurve.slice(Math.max(0, equityCurve.length - keep));
  }, [equityCurve, activeTimeframe]);

const hasPriceData = filteredCurve.some(p => p.price > 0);
const pricePoints  = hasPriceData ? filteredCurve : [];

const priceDomain = hasPriceData
  ? ([`dataMin - 300`, `dataMax + 300`] as const)
  : ([0, 1] as const);

  // ─── Loading skeleton ─────────────────────────────────────────────────────
  if (loading && !summary) {
    return (
      <section className="w-full min-h-screen pb-12 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-fuchsia-50 via-white to-slate-50">
        <OverviewHeader />
        <div className="px-6 mt-8 max-w-7xl mx-auto space-y-5">
          <div className="h-10 w-64 rounded-2xl bg-gray-200 animate-pulse" />
          <div className="grid grid-cols-12 gap-5">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="col-span-3 h-36 rounded-[24px] bg-gray-100 animate-pulse" />
            ))}
          </div>
          <div className="h-[620px] rounded-[28px] bg-gray-100 animate-pulse" />
          <div className="h-[400px] rounded-[28px] bg-gray-100 animate-pulse" />
        </div>
      </section>
    );
  }

  if (error && !summary) {
    return (
      <section className="w-full min-h-screen flex items-center justify-center bg-fuchsia-50">
        <div className="text-center p-8">
          <AlertCircle size={48} className="text-rose-400 mx-auto mb-4" />
          <p className="text-gray-700 font-bold text-lg mb-2">ไม่สามารถโหลดข้อมูล Backtest</p>
          <p className="text-gray-400 text-sm mb-6">{error}</p>
          <button onClick={fetchData}
            className="bg-purple-600 text-white px-6 py-2.5 rounded-xl font-bold hover:bg-purple-700 transition-colors">
            ลองใหม่
          </button>
        </div>
      </section>
    );
  }

  const s = summary!;
  const netPnlSign = s.trade_net_pnl_thb >= 0 ? '+' : '';
  const returnSign = s.risk_total_return_pct >= 0 ? '+' : '';
  const dateRange  = filteredCurve.length >= 2
    ? `${filteredCurve[0].date} – ${filteredCurve[filteredCurve.length - 1].date}` : '—';

  const buyCount         = trades.filter(t => t.signal === 'BUY').length;
  const sellCount        = trades.filter(t => t.signal === 'SELL').length;
  const profitableTrades = trades.filter(t => t.profitable).length;

  // X-axis interval เพื่อไม่ให้ label แน่น
  const xInterval = Math.max(1, Math.floor(filteredCurve.length / 10));

  // Filtered trades for table
  const filteredTrades = trades.filter(t => {
    const matchSignal = signalFilter === 'ALL' || t.signal === signalFilter;
    const matchSearch = !tradeSearch ||
      t.timestamp.includes(tradeSearch) ||
      t.rationale.toLowerCase().includes(tradeSearch.toLowerCase());
    return matchSignal && matchSearch;
  });
  const totalPages  = Math.ceil(filteredTrades.length / PAGE_SIZE);
  const pagedTrades = filteredTrades.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleExport = () => {
    const headers = ['timestamp','signal','confidence','pnl','position_size','stop_loss','take_profit','rationale'];
    const rows    = trades.map(t =>
      [t.timestamp, t.signal, t.confidence, t.pnl, t.position_size, t.stop_loss, t.take_profit,
       `"${t.rationale.replace(/"/g, '""')}"`].join(','));
    const csv  = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a'); a.href = url;
    a.download = `backtest_trades_${s.model_name}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <section id="backtest"
      className="w-full min-h-screen pb-16 bg-[radial-gradient(circle_at_top_right,_var(--tw-gradient-stops))] from-fuchsia-50 via-white to-slate-50">
      <OverviewHeader />

      <div className="px-6 mt-8 relative z-20 max-w-7xl mx-auto">

        {/* ── Title & Actions ──────────────────────────────────────────────── */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <h2 className="text-3xl font-black text-gray-900 tracking-tight">Backtest Report</h2>
            <div className="flex items-center gap-3 mt-1">
              <p className="text-sm text-gray-500 font-medium">
                Model: <span className="text-purple-700 font-bold">{s.model_name}</span>
              </p>
              {lastFetch && (
                <span className="text-[11px] text-gray-400">
                  Updated {lastFetch.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}
              {loading && <RefreshCw size={12} className="text-purple-400 animate-spin" />}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={fetchData} disabled={loading}
              className="flex items-center gap-1.5 border border-purple-200 text-purple-700 px-4 py-2.5 rounded-xl text-sm font-bold hover:bg-purple-50 transition-all disabled:opacity-40">
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} /> Refresh
            </button>
            <button onClick={handleExport}
              className="flex items-center gap-2 bg-gradient-to-r from-purple-900 to-fuchsia-800 text-white px-5 py-2.5 rounded-xl text-sm font-bold hover:shadow-[0_8px_20px_rgba(168,85,247,0.25)] hover:-translate-y-0.5 transition-all duration-300">
              <Download size={16} /> Export Trades
            </button>
          </div>
        </div>

        {/* ── KPI Cards ────────────────────────────────────────────────────── */}
        <div className="grid grid-cols-12 gap-5 mb-5">
          <BacktestMetricCard label="Net PnL"
            value={`${netPnlSign}${s.trade_net_pnl_thb.toFixed(2)}`} unit="THB"
            subValue={`${returnSign}${s.risk_total_return_pct.toFixed(2)}% Return`}
            color="text-emerald-600" icon={<TrendingUp size={22} />} />
          <BacktestMetricCard label="Win Rate"
            value={s.trade_win_rate_pct.toFixed(2)} unit="%"
            subValue={`${s.trade_winning_trades}W / ${s.trade_losing_trades}L Trades`}
            color="text-fuchsia-600" icon={<Target size={22} />} />
          <BacktestMetricCard label="Max Drawdown"
            value={s.risk_mdd_pct.toFixed(2)} unit="%"
            subValue={`Calmar: ${s.trade_calmar_ratio?.toFixed(2) ?? '—'}`}
            color="text-rose-500" icon={<ShieldAlert size={22} />} />
          <BacktestMetricCard label="Profit Factor"
            value={s.trade_profit_factor.toFixed(3)} unit="x"
            subValue={`Expectancy: ${s.trade_expectancy_thb.toFixed(2)} ฿`}
            color="text-purple-600" icon={<Activity size={22} />} />
        </div>

        {/* ── Secondary Stats ───────────────────────────────────────────────── */}
        <div className="grid grid-cols-12 gap-5 mb-6">
          {[
            { label: 'Sharpe Ratio',   value: s.risk_sharpe_ratio?.toFixed(3)              ?? '—' },
            { label: 'Sortino Ratio',  value: s.risk_sortino_ratio?.toFixed(3)             ?? '—' },
            { label: 'Ann. Return',    value: `${s.risk_annualized_return_pct?.toFixed(2)}%` },
            { label: 'LLM Accuracy',   value: `${s.llm_directional_accuracy_pct?.toFixed(1)}%` },
            { label: 'Final Accuracy', value: `${s.final_directional_accuracy_pct?.toFixed(1)}%` },
            { label: 'Session Comply', value: `${s.session_compliance_compliance_pct?.toFixed(1)}%` },
          ].map(({ label, value }) => (
            <div key={label}
              className="col-span-6 md:col-span-2 bg-white/70 backdrop-blur-md rounded-2xl px-5 py-4 border border-gray-100 shadow-sm">
              <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">{label}</p>
              <p className="text-xl font-black text-gray-800">{value}</p>
            </div>
          ))}
        </div>

        {/* ══════════════════════════════════════════════════════════════════ */}
        {/* ── Dual Synchronized Chart Block ──────────────────────────────── */}
        {/* ══════════════════════════════════════════════════════════════════ */}
        <div className="relative bg-white/80 backdrop-blur-xl rounded-[28px] p-8
          shadow-[0_8px_30px_rgba(0,0,0,0.04)] border border-gray-200/60
          hover:border-purple-400/60 transition-colors duration-500 overflow-hidden group mb-6">

          <div className="absolute top-0 left-0 w-full h-[4px] bg-gradient-to-r from-purple-400 via-fuchsia-500 to-pink-500 opacity-80 group-hover:opacity-100 transition-opacity" />
          <div className="absolute -top-32 -right-32 w-96 h-96 bg-gradient-to-br from-purple-100/50 to-transparent rounded-full blur-3xl pointer-events-none" />

          {/* ── Header ─────────────────────────────────────────────────────── */}
          <div className="relative z-10 flex items-start justify-between mb-6 flex-wrap gap-4">
            <div>
              <h3 className="text-xl font-bold text-gray-900 tracking-tight">Gold Price & Portfolio Equity</h3>
              <p className="text-sm text-gray-400 font-medium mt-1">
                {s.risk_candles_total?.toLocaleString()} candles · แสดง {filteredCurve.length} จุด · hover เพื่อดูรายละเอียด
              </p>
            </div>

            <div className="flex flex-col items-end gap-3">
              {/* Timeframe pills */}
              <div className="flex bg-gray-100 rounded-xl p-1 gap-0.5">
                {TIMEFRAMES.map(tf => (
                  <button key={tf.key} onClick={() => setActiveTimeframe(tf.key)}
                    className={`px-3.5 py-1.5 rounded-lg text-[12px] font-black transition-all duration-200 ${
                      activeTimeframe === tf.key
                        ? 'bg-white text-purple-700 shadow-sm ring-1 ring-purple-100'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}>
                    {tf.label}
                  </button>
                ))}
              </div>

              {/* Signal legend */}
              <div className="flex items-center gap-3 text-[10px] font-bold flex-wrap justify-end">
                {[
                  { col: '#10b981', label: 'BUY profit'  },
                  { col: '#f59e0b', label: 'BUY loss'    },
                  { col: '#06b6d4', label: 'SELL profit' },
                  { col: '#f43f5e', label: 'SELL loss'   },
                ].map(({ col, label }) => (
                  <span key={label} className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: col }} />
                    <span style={{ color: col }}>{label}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* ── Chart 1: Gold Price ─────────────────────────────────────────── */}
          <div className="relative z-10">
            <div className="flex items-center gap-2 mb-2 ml-1">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <span className="text-[11px] font-black text-amber-600 uppercase tracking-widest">
                Gold Price (THB) · {dateRange}
              </span>
            </div>

            <div className="h-[300px] w-full">
              {!hasPriceData ? (
                <div className="h-full flex items-center justify-center text-gray-300 text-sm">
                  ไม่มีข้อมูลราคาทอง (close_thai = 0)
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={pricePoints}
                    margin={{ top: 20, right: 20, left: 10, bottom: 0 }}
                    syncId="backtest">
                    <defs>
                      <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%"  stopColor="#f59e0b" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="#f59e0b" stopOpacity={0}   />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis dataKey="date" hide />
                    <YAxis
                      stroke="#d97706" fontSize={10} tickLine={false} axisLine={false} width={75}
                      tickFormatter={v => v > 0 ? v.toLocaleString('th-TH') : ''}
                      domain={priceDomain}
                    />
                    <Tooltip
                      content={<SharedTooltip />}
                      cursor={{ stroke: '#f59e0b', strokeWidth: 1, strokeDasharray: '4 4' }}
                    />
                    <Area type="monotone" dataKey="price"
                      stroke="#d97706" strokeWidth={2}
                      fill="url(#priceGradient)"
                      dot={PriceSignalDot}
                      activeDot={{ r: 7, fill: '#d97706', stroke: '#fff', strokeWidth: 2 }}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          {/* Dashed divider */}
          <div className="relative z-10 mx-2 my-1 border-t border-dashed border-gray-200" />

          {/* ── Chart 2: Portfolio Equity ────────────────────────────────────── */}
          <div className="relative z-10">
            <div className="flex items-center gap-2 mb-2 ml-1 mt-3">
              <span className="w-2 h-2 rounded-full bg-purple-500" />
              <span className="text-[11px] font-black text-purple-600 uppercase tracking-widest">Portfolio Value (THB)</span>
            </div>

            <div className="h-[280px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={filteredCurve}
                  margin={{ top: 10, right: 20, left: 10, bottom: 0 }}
                  syncId="backtest">
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#c026d3" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#c026d3" stopOpacity={0}    />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis
                    dataKey="date" stroke="#94a3b8" fontSize={10}
                    tickLine={false} axisLine={false} dy={8}
                    interval={xInterval}
                  />
                  <YAxis
                    stroke="#9333ea" fontSize={10} tickLine={false} axisLine={false} width={75}
                    tickFormatter={v => v > 0 ? v.toLocaleString('th-TH') : ''}
                    domain={['dataMin - 500', 'dataMax + 500']}
                  />
                  <Tooltip
                    content={<SharedTooltip />}
                    cursor={{ stroke: '#c026d3', strokeWidth: 1, strokeDasharray: '4 4' }}
                  />
                  <Area type="monotone" dataKey="value"
                    stroke="#a21caf" strokeWidth={2.5}
                    fill="url(#equityGradient)"
                    dot={EquitySignalDot}
                    activeDot={{ r: 8, fill: '#86198f', stroke: '#fff', strokeWidth: 2 }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Summary bar */}
          <div className="relative z-10 mt-6 pt-6 border-t border-gray-100 grid grid-cols-4 gap-4 text-center">
            {[
              { label: 'Initial Portfolio', val: `${s.risk_initial_portfolio_thb?.toLocaleString('th-TH', { minimumFractionDigits: 2 })} ฿`, cls: 'text-gray-700' },
              { label: 'Final Portfolio',   val: `${s.risk_final_portfolio_thb?.toLocaleString('th-TH', { minimumFractionDigits: 2 })} ฿`, cls: 'text-emerald-600' },
              { label: 'Total Trades',      val: String(s.trade_total_trades), cls: 'text-gray-700' },
              { label: 'Profitable',        val: String(profitableTrades),      cls: 'text-purple-700' },
            ].map(({ label, val, cls }) => (
              <div key={label}>
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">{label}</p>
                <p className={`text-lg font-black ${cls}`}>{val}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ── Trade History ─────────────────────────────────────────────────── */}
        <div className="bg-white/80 backdrop-blur-xl rounded-[28px] shadow-[0_8px_30px_rgba(0,0,0,0.04)] border border-gray-200/60 overflow-hidden">

          <div className="px-8 py-6 border-b border-gray-100">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h3 className="text-xl font-bold text-gray-900 tracking-tight">Trade History</h3>
                <p className="text-sm text-gray-400 mt-1 font-medium">
                  {filteredTrades.length} trades · คลิกที่แถวเพื่อดูเหตุผลการซื้อขาย
                </p>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <div className="flex bg-gray-100 rounded-xl p-1 gap-0.5">
                  {(['ALL', 'BUY', 'SELL'] as const).map(f => (
                    <button key={f} onClick={() => { setSignalFilter(f); setPage(1); }}
                      className={`px-3.5 py-1.5 rounded-lg text-[12px] font-black transition-all duration-200 ${
                        signalFilter === f
                          ? f === 'BUY'  ? 'bg-emerald-500 text-white shadow-sm'
                          : f === 'SELL' ? 'bg-rose-500 text-white shadow-sm'
                          : 'bg-white text-purple-700 shadow-sm'
                          : 'text-gray-500 hover:text-gray-700'
                      }`}>
                      {f === 'ALL' ? `All ${trades.length}` : f === 'BUY' ? `↑ ${buyCount}` : `↓ ${sellCount}`}
                    </button>
                  ))}
                </div>
                <div className="relative">
                  <input type="text" placeholder="ค้นหา... (วันที่ / เหตุผล)"
                    value={tradeSearch}
                    onChange={e => { setTradeSearch(e.target.value); setPage(1); }}
                    className="pl-4 pr-10 py-2 rounded-xl border border-gray-200 text-[12px] font-medium bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-purple-300 focus:border-purple-400 w-56"
                  />
                  <Filter size={13} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                </div>
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/60">
                  <th className="py-3 pl-5 pr-2 text-left text-[10px] font-black text-gray-400 uppercase tracking-widest w-10">#</th>
                  <th className="py-3 px-3 text-left text-[10px] font-black text-gray-400 uppercase tracking-widest">Time</th>
                  <th className="py-3 px-3 text-left text-[10px] font-black text-gray-400 uppercase tracking-widest">Signal</th>
                  <th className="py-3 px-3 text-left text-[10px] font-black text-gray-400 uppercase tracking-widest">Confidence</th>
                  <th className="py-3 px-3 text-left text-[10px] font-black text-gray-400 uppercase tracking-widest">Price (฿)</th>
                  <th className="py-3 px-3 text-left text-[10px] font-black text-gray-400 uppercase tracking-widest">Net PnL</th>
                  <th className="py-3 px-3 text-left text-[10px] font-black text-gray-400 uppercase tracking-widest">Result</th>
                  <th className="py-3 pr-4 pl-2 w-8" />
                </tr>
              </thead>
              <tbody>
                {pagedTrades.length === 0 ? (
                  <tr><td colSpan={8} className="text-center py-16 text-gray-400 font-medium">
                    {trades.length === 0 ? (
                      <div>
                        <Clock size={36} className="mx-auto mb-3 text-gray-300" />
                        <p>ไม่มีข้อมูล Trade History</p>
                        <p className="text-sm mt-1 text-gray-300">ตรวจสอบว่า API /api/backtest/trades พร้อมใช้งาน</p>
                      </div>
                    ) : <p>ไม่พบผลลัพธ์ที่ค้นหา</p>}
                  </td></tr>
                ) : pagedTrades.map((trade, i) => (
                  <TradeHistoryRow key={`${trade.timestamp}-${i}`}
                    trade={trade} index={(page - 1) * PAGE_SIZE + i} />
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="px-8 py-5 border-t border-gray-100 flex items-center justify-between">
              <p className="text-[12px] text-gray-400 font-medium">
                แสดง {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filteredTrades.length)} จาก {filteredTrades.length} รายการ
              </p>
              <div className="flex items-center gap-2">
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                  className="px-3 py-1.5 rounded-lg border border-gray-200 text-[12px] font-bold text-gray-600 hover:bg-gray-50 disabled:opacity-40 transition-all">← ก่อนหน้า</button>
                <div className="flex gap-1">
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    const p = page <= 3 ? i + 1 : page - 2 + i;
                    if (p < 1 || p > totalPages) return null;
                    return (
                      <button key={p} onClick={() => setPage(p)}
                        className={`w-8 h-8 rounded-lg text-[12px] font-bold transition-all ${
                          p === page ? 'bg-purple-600 text-white shadow-sm'
                                     : 'border border-gray-200 text-gray-500 hover:bg-gray-50'}`}>
                        {p}
                      </button>
                    );
                  })}
                </div>
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
                  className="px-3 py-1.5 rounded-lg border border-gray-200 text-[12px] font-bold text-gray-600 hover:bg-gray-50 disabled:opacity-40 transition-all">ถัดไป →</button>
              </div>
            </div>
          )}
        </div>

      </div>
    </section>
  );
};

// ─── Metric Card ───────────────────────────────────────────────────────────────
const BacktestMetricCard = ({
  label, value, unit, subValue, color, icon
}: {
  label: string; value: string; unit: string;
  subValue: string; color: string; icon: React.ReactNode;
}) => (
  <div className="col-span-12 md:col-span-3 relative bg-white/80 backdrop-blur-md rounded-[24px] p-6
    border border-gray-200/80 shadow-[0_4px_15px_rgba(0,0,0,0.02)]
    transition-all duration-300 ease-out
    hover:-translate-y-1 hover:shadow-[0_12px_30px_rgba(192,38,211,0.15)]
    hover:border-purple-300 hover:ring-4 hover:ring-purple-500/10
    group overflow-hidden cursor-default">
    <div className="absolute -top-10 -right-10 w-28 h-28 bg-gradient-to-br from-fuchsia-100 to-transparent rounded-full blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
    <div className="relative z-10 flex justify-between items-start mb-5">
      <div className={`p-3.5 rounded-2xl bg-gray-50/80 group-hover:bg-white group-hover:shadow-sm transition-all duration-300 ${color}`}>{icon}</div>
      <div className="p-2 bg-gray-50 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300">
        <ArrowUpRight size={16} className="text-gray-400 group-hover:text-purple-500" />
      </div>
    </div>
    <div className="relative z-10">
      <p className="text-[11px] text-gray-500 uppercase font-black tracking-widest mb-1.5">{label}</p>
      <div className="flex items-baseline gap-1.5">
        <span className="text-3xl font-black text-gray-900 tracking-tight group-hover:text-purple-950 transition-colors">{value}</span>
        <span className={`text-sm font-bold ${color}`}>{unit}</span>
      </div>
      <p className="text-[12px] font-bold text-gray-400 mt-2 flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full ${color.replace('text-', 'bg-')}`} />
        {subValue}
      </p>
    </div>
  </div>
);
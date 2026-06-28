import React, { useState, useEffect, useCallback, useMemo } from 'react';
import Chart from 'react-apexcharts';
import { OverviewHeader } from '../overview/OverviewHeader';
import {
  TrendingUp, TrendingDown, RefreshCw, Newspaper,
  Globe, DollarSign, BarChart2, AlertCircle, Coins,
  Clock, Wifi, WifiOff, ArrowUpRight, ArrowDownRight,
  Activity, Radio, Zap
} from 'lucide-react';

// ─── Types ────────────────────────────────────────────────────────────────────
interface Snapshot {
  ask_96: number; bid_96: number; spot_usd: number; usd_thb: number;
  spread: number; timestamp: string;
  ask_chg_24h: number; ask_pct_24h: number;
  spot_chg_24h: number; spot_pct_24h: number;
  rate_chg_24h: number; rate_pct_24h: number;
  ask_pct_7d: number; spot_pct_7d: number;
}
interface HistoryBar {
  time: number; ask_96: number; bid_96: number;
  high_ask: number; low_ask: number;
  spot: number; usd_thb: number; spread: number; n: number;
}
interface NewsItem {
  id: number; title: string; url: string; source: string;
  published_at: string; category: string;
  impact_level: 'HIGH' | 'MEDIUM' | 'LOW';
  sentiment: number; sentiment_label: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  impact_score: number; event_type: string;
  actual?: number; forecast?: number; value_diff?: number;
}
type Timeframe = '15m' | '1H' | '4H' | '1D' | '1W';
type ChartMode = 'thai_gold' | 'spot' | 'usd_thb' | 'spread';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// ─── Utility ──────────────────────────────────────────────────────────────────
const fmtTHB  = (n: number) => n.toLocaleString('th-TH', { maximumFractionDigits: 0 });
const fmtUSD  = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 });
const fmtPct  = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
const timeAgo = (iso: string) => {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60)    return `${Math.floor(diff)}s ago`;
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// ─── Small components ─────────────────────────────────────────────────────────
const ChangeBadge = ({ pct }: { pct: number }) => {
  const up = pct >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 text-[11px] font-bold px-2 py-0.5 rounded-full ${
      up ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-500'
    }`}>
      {up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
      {fmtPct(pct)}
    </span>
  );
};

const ImpactDot = ({ level }: { level: string }) => {
  const color = level === 'HIGH' ? 'bg-rose-500' : level === 'MEDIUM' ? 'bg-amber-400' : 'bg-slate-300';
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${color} flex-shrink-0 mt-0.5`} />;
};

const SentimentBar = ({ score }: { score: number }) => (
  <div className="flex items-center gap-1.5">
    <div className="w-12 h-1 rounded-full bg-gray-100 overflow-hidden">
      <div
        className={`h-full rounded-full ${score >= 0 ? 'bg-emerald-400' : 'bg-rose-400'}`}
        style={{ width: `${Math.min(Math.abs(score) * 100, 100)}%` }}
      />
    </div>
    <span className={`text-[9px] font-bold ${score >= 0 ? 'text-emerald-500' : 'text-rose-400'}`}>
      {score >= 0 ? '+' : ''}{score.toFixed(2)}
    </span>
  </div>
);

// ─── Main ─────────────────────────────────────────────────────────────────────
export const MarketSnapshot = () => {
  const [snap,    setSnap]    = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<HistoryBar[]>([]);
  const [news,    setNews]    = useState<NewsItem[]>([]);

  const [tf,           setTf]           = useState<Timeframe>('1H');
  const [chartMode,    setChartMode]    = useState<ChartMode>('thai_gold');
  const [newsCategory, setNewsCategory] = useState<string>('all');
  const [loading,      setLoading]      = useState(true);
  const [newsLoading,  setNewsLoading]  = useState(true);
  const [lastSync,     setLastSync]     = useState<Date | null>(null);
  const [online,       setOnline]       = useState(true);

  const fetchMarket = useCallback(async () => {
    try {
      const [snapRes, histRes] = await Promise.all([
        fetch(`${BASE}/api/market/snapshot`),
        fetch(`${BASE}/api/market/history?tf=${tf}&source=ig&limit=500`),
      ]);
      if (snapRes.ok) setSnap(await snapRes.json());
      if (histRes.ok) setHistory(await histRes.json());
      
      setLastSync(new Date());
      setOnline(true);
    } catch (error) {
      console.error("Failed to fetch market data:", error); // แนะนำให้ใส่ log ไว้ดู error ด้วยครับ
      setOnline(false);
    } finally {
      setLoading(false);
    }
  }, [tf]);

  const fetchNews = useCallback(async () => {
    setNewsLoading(true);
    try {
      const params = newsCategory === 'all' ? '' : `&category=${newsCategory}`;
      const res = await fetch(`${BASE}/api/market/news?limit=40${params}`);
      if (res.ok) setNews(await res.json());
    } catch { /* silent */ }
    finally { setNewsLoading(false); }
  }, [newsCategory]);

  useEffect(() => { fetchMarket(); }, [fetchMarket]);
  useEffect(() => { fetchNews(); },  [fetchNews]);
  useEffect(() => {
    const id = setInterval(fetchMarket, 60_000);
    return () => clearInterval(id);
  }, [fetchMarket]);

  const chartSeries = useMemo(() => {
    if (!history.length) return [];
    const data = history.map(d => ({
      x: d.time,
      y: chartMode === 'thai_gold' ? d.ask_96
       : chartMode === 'spot'      ? d.spot
       : chartMode === 'usd_thb'   ? d.usd_thb
       : d.spread,
    }));
    const names: Record<ChartMode, string> = { thai_gold: 'Thai Gold (Sell)', spot: 'XAU/USD', usd_thb: 'USD/THB', spread: 'Spread' };
    return [{ name: names[chartMode], data }];
  }, [history, chartMode]);

  const chartColor = chartMode === 'thai_gold' ? '#824199'
    : chartMode === 'spot'    ? '#3b82f6'
    : chartMode === 'usd_thb' ? '#10b981'
    : '#f59e0b';

  const chartOptions: any = useMemo(() => ({
    chart: { type: 'area', background: 'transparent', toolbar: { show: false }, animations: { enabled: false } },
    colors: [chartColor],
    fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.2, opacityTo: 0.0 } },
    stroke: { curve: 'smooth', width: 2.5 },
    dataLabels: { enabled: false },
    xaxis: {
      type: 'datetime',
      labels: { style: { colors: '#9ca3af', fontSize: '10px', fontWeight: 600 }, datetimeUTC: false },
      axisBorder: { show: false }, axisTicks: { show: false },
    },
    yaxis: {
      labels: {
        style: { colors: '#9ca3af', fontSize: '11px', fontWeight: 700 },
        formatter: (v: number) =>
          chartMode === 'usd_thb' ? v.toFixed(2)
          : chartMode === 'spot'  ? `$${fmtUSD(v)}`
          : `฿${fmtTHB(v)}`,
      },
    },
    grid: { borderColor: '#f1f5f9', strokeDashArray: 4 },
    tooltip: {
      theme: 'light',
      x: { format: 'dd MMM HH:mm' },
      y: { formatter: (v: number) =>
        chartMode === 'usd_thb' ? v.toFixed(4)
        : chartMode === 'spot'  ? `$${v.toFixed(2)}`
        : `฿${fmtTHB(v)}` },
    },
  }), [chartMode, chartColor]);

  return (
    <section className="w-full min-h-screen pb-12 relative overflow-hidden" style={{ background: '#FCFBF7' }}>

      {/* Background orbs */}
      <div className="absolute top-[-10%] left-[-10%] w-[500px] h-[500px] bg-[#824199]/5 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[10%] right-[-5%] w-[400px] h-[400px] bg-emerald-500/5 rounded-full blur-[100px] pointer-events-none" />

      <OverviewHeader />

      <div className="px-6 mt-12 relative z-20 max-w-7xl mx-auto">

        {/* Page Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-10">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Globe size={16} className="text-[#824199]" />
              <p className="text-[10px] font-bold text-[#824199] uppercase tracking-[0.3em]">Live Monitor</p>
            </div>
            <h1 className="text-4xl font-black text-gray-900 tracking-tight">Market Snapshot</h1>
          </div>

          <div className="flex items-center gap-3">
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-[10px] font-black uppercase tracking-widest ${
              online ? 'border-emerald-200 bg-emerald-50 text-emerald-600' : 'border-rose-200 bg-rose-50 text-rose-500'
            }`}>
              {online ? <Radio size={11} className="text-emerald-500 animate-pulse" /> : <WifiOff size={11} />}
              {online ? 'Live' : 'Offline'}
            </div>
            {lastSync && (
              <span className="text-[11px] font-medium text-gray-400 hidden sm:flex items-center gap-1">
                <Clock size={11} /> {lastSync.toLocaleTimeString('th-TH')}
              </span>
            )}
            <button
              onClick={() => { fetchMarket(); fetchNews(); }}
              className="p-2 rounded-xl border border-gray-200 text-gray-400 hover:border-[#824199]/40 hover:text-[#824199] transition-all active:scale-95 bg-white shadow-sm"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        {/* 4 Price Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {([
            {
              label: 'Thai Gold Sell', sub: 'Hua Seng Heng 96.5%',
              value: snap?.ask_96,     unit: 'THB / g',
              pct: snap?.ask_pct_24h,  fmtVal: (v: number) => `฿${fmtTHB(v)}`,
              icon: <Zap size={16} />, color: '#824199', bg: 'bg-purple-50', border: 'border-purple-100',
              mode: 'thai_gold' as ChartMode,
            },
            {
              label: 'Thai Gold Buy', sub: 'Hua Seng Heng 96.5%',
              value: snap?.bid_96,     unit: 'THB / g',
              pct: snap?.ask_pct_24h,  fmtVal: (v: number) => `฿${fmtTHB(v)}`,
              icon: <Coins size={16} />, color: '#10b981', bg: 'bg-emerald-50', border: 'border-emerald-100',
              mode: 'thai_gold' as ChartMode,
            },
            {
              label: 'XAU / USD', sub: 'Global Spot Price',
              value: snap?.spot_usd,   unit: 'USD / oz',
              pct: snap?.spot_pct_24h, fmtVal: (v: number) => `$${fmtUSD(v)}`,
              icon: <Globe size={16} />, color: '#3b82f6', bg: 'bg-blue-50', border: 'border-blue-100',
              mode: 'spot' as ChartMode,
            },
            {
              label: 'USD / THB', sub: 'Exchange Rate',
              value: snap?.usd_thb,    unit: 'THB / USD',
              pct: snap?.rate_pct_24h, fmtVal: (v: number) => v.toFixed(4),
              icon: <DollarSign size={16} />, color: '#f59e0b', bg: 'bg-amber-50', border: 'border-amber-100',
              mode: 'usd_thb' as ChartMode,
            },
          ] as const).map(card => {
            const active = chartMode === card.mode;
            return (
              <button
                key={card.label}
                onClick={() => setChartMode(card.mode)}
                className={`text-left p-5 rounded-2xl border bg-white transition-all hover:shadow-md flex flex-col justify-between h-[130px] ${
                  active ? 'border-[#824199]/30 shadow-md ring-1 ring-[#824199]/20' : 'border-gray-100 shadow-sm'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className={`p-2 rounded-xl border ${card.bg} ${card.border}`} style={{ color: card.color }}>
                    {card.icon}
                  </div>
                  <span className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">{card.unit}</span>
                </div>
                <div>
                  <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-0.5">{card.label}</p>
                  {loading || !card.value ? (
                    <div className="h-7 w-28 bg-gray-100 rounded animate-pulse" />
                  ) : (
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-2xl font-black text-gray-900 tracking-tight">{card.fmtVal(card.value)}</span>
                      {card.pct !== undefined && <ChangeBadge pct={card.pct} />}
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Chart + News */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

          {/* Chart Panel */}
          <div className="xl:col-span-2 bg-white rounded-[28px] border border-gray-100 shadow-sm p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
              <div className="flex bg-gray-50 p-1 rounded-xl border border-gray-100">
                {(['thai_gold', 'spot', 'usd_thb', 'spread'] as ChartMode[]).map(key => {
                  const labels: Record<ChartMode, string> = { thai_gold: 'Gold 96.5', spot: 'XAU/USD', usd_thb: 'USD/THB', spread: 'Spread' };
                  return (
                    <button key={key} onClick={() => setChartMode(key)}
                      className={`px-3 py-1.5 rounded-lg text-[10px] font-black tracking-widest transition-all ${
                        chartMode === key ? 'bg-white text-[#824199] shadow-sm' : 'text-gray-400 hover:text-gray-700'
                      }`}>
                      {labels[key]}
                    </button>
                  );
                })}
              </div>
              <div className="flex bg-gray-50 p-1 rounded-xl border border-gray-100">
                {(['15m', '1H', '4H', '1D', '1W'] as Timeframe[]).map(t => (
                  <button key={t} onClick={() => setTf(t)}
                    className={`px-3 py-1.5 rounded-lg text-[10px] font-black tracking-widest transition-all ${
                      tf === t ? 'bg-white text-[#824199] shadow-sm' : 'text-gray-400 hover:text-gray-700'
                    }`}>
                    {t}
                  </button>
                ))}
              </div>
            </div>

            {snap && (
              <div className="flex flex-wrap gap-5 mb-4 px-1 pb-4 border-b border-gray-50">
                <div>
                  <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">Spread</p>
                  <p className="text-sm font-black text-[#824199]">฿{snap.spread.toFixed(1)}</p>
                </div>
                <div><p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">24h Gold</p><ChangeBadge pct={snap.ask_pct_24h} /></div>
                <div><p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">24h Spot</p><ChangeBadge pct={snap.spot_pct_24h} /></div>
                <div><p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">7d Gold</p><ChangeBadge pct={snap.ask_pct_7d} /></div>
                <div className="ml-auto hidden sm:block">
                  <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">Data points</p>
                  <p className="text-sm font-black text-gray-500">{history.length.toLocaleString()}</p>
                </div>
              </div>
            )}

            {history.length === 0 ? (
              <div className="h-72 flex flex-col items-center justify-center text-gray-300">
                <BarChart2 size={36} className="mb-2" />
                <p className="text-sm font-bold">Loading chart data…</p>
              </div>
            ) : (
              <Chart options={chartOptions} series={chartSeries} type="area" height={360} />
            )}
          </div>

          {/* News Panel */}
          <div className="bg-white rounded-[28px] border border-gray-100 shadow-sm flex flex-col overflow-hidden">
            <div className="p-5 border-b border-gray-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Newspaper size={15} className="text-[#824199]" />
                <span className="text-[11px] font-black text-gray-900 uppercase tracking-widest">Market News</span>
              </div>
              <div className="flex gap-0.5 p-0.5 rounded-lg bg-gray-50 border border-gray-100">
                {(['all', 'gold', 'forex', 'macro'] as const).map(cat => (
                  <button key={cat} onClick={() => setNewsCategory(cat)}
                    className={`px-2 py-0.5 rounded text-[8px] font-black tracking-widest transition-all capitalize ${
                      newsCategory === cat ? 'bg-white text-[#824199] shadow-sm' : 'text-gray-400 hover:text-gray-600'
                    }`}>
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-gray-50" style={{ maxHeight: 490 }}>
              {newsLoading ? (
                Array.from({ length: 7 }).map((_, i) => (
                  <div key={i} className="p-4 space-y-2">
                    <div className="h-2.5 bg-gray-100 rounded animate-pulse w-3/4" />
                    <div className="h-2 bg-gray-100 rounded animate-pulse w-1/2" />
                  </div>
                ))
              ) : news.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-40 text-gray-300">
                  <AlertCircle size={24} className="mb-2" />
                  <p className="text-xs font-bold">No news found</p>
                </div>
              ) : news.map(item => (
                <a key={item.id} href={item.url} target="_blank" rel="noopener noreferrer"
                  className="block p-3.5 hover:bg-gray-50/80 transition-colors group">
                  <div className="flex items-start gap-1.5 mb-1.5">
                    <ImpactDot level={item.impact_level} />
                    <span className={`text-[9px] font-black uppercase tracking-widest ${
                      item.sentiment_label === 'BULLISH' ? 'text-emerald-500'
                      : item.sentiment_label === 'BEARISH' ? 'text-rose-500'
                      : 'text-gray-400'
                    }`}>{item.sentiment_label}</span>
                    <span className="ml-auto text-[9px] text-gray-400 flex-shrink-0">{timeAgo(item.published_at)}</span>
                  </div>
                  <p className="text-[12px] font-semibold text-gray-700 leading-snug group-hover:text-gray-900 transition-colors line-clamp-2 mb-2">
                    {item.title}
                  </p>
                  <div className="flex items-center justify-between">
                    <span className="text-[9px] font-bold text-gray-400 uppercase tracking-widest">
                      {item.source}{item.category && item.category !== 'general' && <span className="ml-1 text-gray-300">· {item.category}</span>}
                    </span>
                    <SentimentBar score={item.sentiment} />
                  </div>
                  {item.actual !== undefined && item.forecast !== undefined && (
                    <div className="mt-1.5 flex gap-3 text-[9px] font-mono">
                      <span className="text-gray-400">Act: <span className="text-gray-700 font-bold">{item.actual}</span></span>
                      <span className="text-gray-400">Fcst: <span className="text-gray-500">{item.forecast}</span></span>
                      {item.value_diff !== undefined && (
                        <span className={item.value_diff >= 0 ? 'text-emerald-500' : 'text-rose-500'}>
                          Δ{item.value_diff >= 0 ? '+' : ''}{item.value_diff}
                        </span>
                      )}
                    </div>
                  )}
                </a>
              ))}
            </div>

            <div className="p-3 border-t border-gray-50 flex items-center justify-between">
              <span className="text-[9px] text-gray-400 font-medium">{news.length} articles</span>
              <button onClick={fetchNews} className="text-[9px] font-bold text-gray-400 hover:text-[#824199] transition-colors flex items-center gap-1">
                Refresh <RefreshCw size={9} />
              </button>
            </div>
          </div>
        </div>

        {/* Bottom stat row */}
        {snap && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5">
            {[
              { label: 'Buy-Sell Spread', value: `฿${snap.spread.toFixed(1)}`, sub: 'Thai Gold 96.5%', color: 'text-[#824199]' },
              { label: '24h Gold Change', value: fmtPct(snap.ask_pct_24h), sub: `฿${snap.ask_chg_24h >= 0 ? '+' : ''}${snap.ask_chg_24h.toFixed(0)} THB`, color: snap.ask_pct_24h >= 0 ? 'text-emerald-600' : 'text-rose-500' },
              { label: '24h Spot Change', value: fmtPct(snap.spot_pct_24h), sub: `$${snap.spot_chg_24h >= 0 ? '+' : ''}${snap.spot_chg_24h.toFixed(2)}`, color: snap.spot_pct_24h >= 0 ? 'text-emerald-600' : 'text-rose-500' },
              { label: '24h USD/THB', value: fmtPct(snap.rate_pct_24h), sub: `${snap.rate_chg_24h >= 0 ? '+' : ''}${snap.rate_chg_24h.toFixed(4)}`, color: snap.rate_pct_24h >= 0 ? 'text-emerald-600' : 'text-rose-500' },
            ].map(m => (
              <div key={m.label} className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
                <p className="text-[9px] font-black text-gray-400 uppercase tracking-widest mb-1">{m.label}</p>
                <p className={`text-xl font-black ${m.color}`}>{m.value}</p>
                <p className="text-[10px] text-gray-400 mt-0.5">{m.sub}</p>
              </div>
            ))}
          </div>
        )}

      </div>
    </section>
  );
};

export default MarketSnapshot;
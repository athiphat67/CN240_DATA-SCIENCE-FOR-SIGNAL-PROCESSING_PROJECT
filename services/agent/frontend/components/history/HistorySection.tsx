'use client';
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { OverviewHeader } from '../overview/OverviewHeader'; // <-- เพิ่มบรรทัดนี้


// ── Config ────────────────────────────────────────────────────────────────────
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const PAGE_SIZE = 50;

// ── API helpers ───────────────────────────────────────────────────────────────
async function apiFetch(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ── Theme Design Tokens (Nakkhutthong Theme) ──────────────────────────────────
const C = {
  brandDark: '#120822', // Deep purple/black from header
  brandPurple:'#2B164D', 
  gold:      '#FBBF24', // Premium Gold
  goldLight: '#FEF3C7',
  goldBg:    '#FFFBEB',
  green:     '#059669', // Profit green
  greenBg:   '#D1FAE5',
  red:       '#DC2626', // Loss red
  redBg:     '#FEE2E2',
  blue:      '#2563EB',
  blueBg:    '#DBEAFE',
  orange:    '#EA580C',
  gray:      '#6B7280',
  grayBg:    '#F3F4F6',
  border:    '#E5E7EB',
  borderLight:'#F1F5F9',
  text:      '#1F2937',
  textDark:  '#111827',
  muted:     '#9CA3AF',
  bg:        '#F9FAFB', // Light gray background for the whole page
  surface:   '#FFFFFF', // Pure white for cards
};

// ── Shared UI Styles ──────────────────────────────────────────────────────────
const cardStyle = {
  background: C.surface,
  borderRadius: '20px',
  border: `1px solid ${C.borderLight}`,
  boxShadow: '0 4px 15px rgba(0, 0, 0, 0.03)',
  overflow: 'hidden',
};

// ── Badge components ──────────────────────────────────────────────────────────
function SignalBadge({ signal }) {
  const cfg = {
    BUY:  { bg: C.greenBg,  color: C.green },
    SELL: { bg: C.redBg,    color: C.red },
    HOLD: { bg: C.goldBg,   color: '#D97706' }, // Yellow/Gold for HOLD
  }[signal] || { bg: C.goldBg, color: '#D97706' };
  
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: '0.05em',
      padding: '4px 10px', borderRadius: '12px',
      background: cfg.bg, color: cfg.color,
      textTransform: 'uppercase', display: 'inline-block'
    }}>{signal || 'HOLD'}</span>
  );
}

function StepBadge({ type }) {
  const cfg = {
    THOUGHT_FINAL: { bg: '#F3E8FF', color: '#7E22CE' },
    TOOL_CALL:     { bg: '#E0E7FF',  color: '#4338CA' },
    THOUGHT:       { bg: '#FEF3C7',  color: '#B45309' },
  }[type] || { bg: C.grayBg, color: C.gray };
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, letterSpacing: '0.05em',
      padding: '4px 8px', borderRadius: '8px',
      background: cfg.bg, color: cfg.color,
      textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>{type || '—'}</span>
  );
}

function ActionBadge({ action }) {
  const isB = action === 'BUY';
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, letterSpacing: '0.05em',
      padding: '4px 10px', borderRadius: '12px',
      background: isB ? C.greenBg : C.redBg,
      color: isB ? C.green : C.red,
      textTransform: 'uppercase',
    }}>{action}</span>
  );
}

function ConfBar({ value, max = 100 }) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const color = pct >= 80 ? C.green : pct >= 55 ? '#F59E0B' : C.red;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: C.textDark, width: 36, textAlign: 'right',
        fontVariantNumeric: 'tabular-nums' }}>
        {Math.round(pct)}%
      </div>
      <div style={{ flex: 1, height: 6, background: C.grayBg, borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3,
          transition: 'width 0.5s ease-in-out' }} />
      </div>
    </div>
  );
}

// ── Table helpers ─────────────────────────────────────────────────────────────
function Th({ children, right, center }) {
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, color: C.muted,
      letterSpacing: '0.05em', textTransform: 'uppercase',
      textAlign: right ? 'right' : center ? 'center' : 'left',
    }}>{children}</div>
  );
}

function Cell({ children, right, center, mono, muted, small }) {
  return (
    <div style={{
      fontSize: small ? 11 : 13, fontWeight: muted ? 400 : 600,
      color: muted ? C.muted : C.textDark,
      textAlign: right ? 'right' : center ? 'center' : 'left',
      fontFamily: mono ? "'JetBrains Mono', 'Fira Code', monospace" : 'inherit',
      lineHeight: 1.4,
    }}>{children}</div>
  );
}

function Sub({ children }) {
  return <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{children}</div>;
}

// ── Expandable Row wrapper ────────────────────────────────────────────────────
function DetailItem({ label, value, mono, color }) {
  return (
    <div style={{ background: '#FFFFFF', padding: '12px 16px', borderRadius: '12px', border: `1px solid ${C.borderLight}` }}>
      <div style={{ fontSize: 9, fontWeight: 700, color: C.muted, letterSpacing: '0.05em',
        textTransform: 'uppercase', marginBottom: 6 }}>{label}</div>
      <div style={{
        fontSize: 13, fontWeight: 600, color: color || C.textDark,
        fontFamily: mono ? "'JetBrains Mono', monospace" : 'inherit',
        wordBreak: 'break-word',
      }}>{value || '—'}</div>
    </div>
  );
}

// ── Load More Button ──────────────────────────────────────────────────────────
function LoadMoreBtn({ onClick, loading, hasMore }) {
  if (!hasMore) return (
    <div style={{ padding: '24px', textAlign: 'center', fontSize: 11, color: C.muted,
      fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
      — End of records —
    </div>
  );
  return (
    <div style={{ padding: '20px', textAlign: 'center' }}>
      <button onClick={onClick} disabled={loading} style={{
        padding: '10px 28px', borderRadius: '100px', border: `1px solid ${C.border}`,
        background: 'white', fontSize: 12, fontWeight: 600, color: C.brandPurple, // changed from C.text
        cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
        boxShadow: '0 2px 4px rgba(0,0,0,0.02)', transition: 'all 0.2s'
      }}>
        {loading ? 'Loading...' : 'Load More'}
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// RUNS TAB
// ─────────────────────────────────────────────────────────────────────────────
function RunsTab({ data, loadMore, loadingMore, hasMore }) {
  const [expanded, setExpanded] = useState(null);
  const toggle = (id) => setExpanded(expanded === id ? null : id);

  const COL = '1.6fr 0.8fr 0.8fr 1fr 1.4fr 1fr 0.8fr 0.4fr';

  return (
    <div>
      <div style={{
        display: 'grid', gridTemplateColumns: COL,
        padding: '16px 24px', background: C.surface,
        borderBottom: `1px solid ${C.borderLight}`, gap: 12,
      }}>
        <Th>Run ID · Time</Th>
        <Th>Signal</Th>
        <Th center>Confidence</Th>
        <Th right>Gold Price (THB)</Th>
        <Th center>Indicators</Th>
        <Th>Trend · Quality</Th>
        <Th right>Exec Time</Th>
        <Th />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {data.map((r) => {
          const open = expanded === r.id;
          return (
            <div key={r.id}>
              <div
                onClick={() => toggle(r.id)}
                style={{
                  display: 'grid', gridTemplateColumns: COL,
                  padding: '16px 24px', gap: 12, alignItems: 'center',
                  borderBottom: `1px solid ${C.borderLight}`,
                  cursor: 'pointer',
                  background: open ? C.bg : 'white',
                  transition: 'all 0.2s ease',
                }}
                onMouseEnter={e => { if (!open) e.currentTarget.style.background = '#FCFDFE'; }}
                onMouseLeave={e => { if (!open) e.currentTarget.style.background = 'white'; }}
              >
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.textDark }}>
                    #{r.id}
                    {r.is_weekend && (
                      <span style={{ marginLeft: 8, fontSize: 9, background: C.goldLight,
                        color: '#92400E', padding: '2px 6px',
                        borderRadius: '6px', fontWeight: 700 }}>WKD</span>
                    )}
                  </div>
                  <Sub>{r.run_at?.slice(0, 19)?.replace('T', ' ')}</Sub>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>{r.interval_tf} · {r.provider?.split(':').pop()?.slice(0, 16)}</div>
                </div>

                <div><SignalBadge signal={r.signal} /></div>
                {/* 👇 แก้บรรทัดนี้ 👇 */}
                <div><ConfBar value={r.confidence * 100} /></div>

                <div style={{ textAlign: 'right' }}>
                  <Cell right mono>{r.gold_price_thb?.toLocaleString()} ฿</Cell>
                  <Sub>${(r.gold_price_thb / (r.usd_thb_rate || 32)).toFixed(0)} USD</Sub>
                </div>

                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 12, color: C.textDark, fontFamily: "'JetBrains Mono', monospace" }}>
                    RSI <span style={{ color: r.rsi > 70 ? C.red : r.rsi < 30 ? C.green : C.textDark,
                      fontWeight: 700 }}>{r.rsi?.toFixed(1)}</span>
                    <span style={{ color: C.border, margin: '0 6px' }}>|</span>
                    BB <span style={{ fontWeight: 600, color: '#7C3AED' }}>{r.bb_pct_b?.toFixed(2)}</span>
                  </div>
                  <div style={{ fontSize: 11, color: C.muted, fontFamily: "'JetBrains Mono', monospace", marginTop: 4 }}>
                    MACD {r.macd_histogram >= 0 ? '+' : ''}{r.macd_histogram?.toFixed(3)}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.textDark }}>{r.trend}</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>{r.data_quality}</div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <Cell right mono>{r.execution_time_ms?.toFixed(0)}ms</Cell>
                  <Sub>{r.iterations_used}it · {r.tool_calls_used}tc</Sub>
                </div>

                <div style={{ textAlign: 'center', color: C.brandPurple, fontSize: 18,
                  transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.3s ease', fontWeight: 300 }}>›</div>
              </div>

              {open && (
                <div style={{
                  background: C.bg,
                  borderBottom: `1px solid ${C.borderLight}`,
                  padding: '20px 24px',
                }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 16 }}>
                    <DetailItem label="Entry Price THB" value={`${r.entry_price_thb?.toLocaleString()} ฿`} mono />
                    <DetailItem label="Stop Loss THB"   value={`${r.stop_loss_thb?.toLocaleString()} ฿`} mono color={C.red} />
                    <DetailItem label="Take Profit THB" value={`${r.take_profit_thb?.toLocaleString()} ฿`} mono color={C.green} />
                    <DetailItem label="USD/THB Rate"    value={r.usd_thb_rate?.toFixed(4)} mono />
                    <DetailItem label="ATR (THB)"       value={r.atr_thb?.toFixed(2)} mono />
                  </div>
                  <div style={{ background: 'white', padding: '16px', borderRadius: '12px', border: `1px solid ${C.borderLight}` }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: C.brandPurple, letterSpacing: '0.05em',
                      textTransform: 'uppercase', marginBottom: 8 }}>AI Rationale</div>
                    <div style={{ fontSize: 13, color: C.text, lineHeight: 1.6 }}>{r.rationale}</div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <LoadMoreBtn onClick={loadMore} loading={loadingMore} hasMore={hasMore} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// TRADES TAB
// ─────────────────────────────────────────────────────────────────────────────
function TradesTab({ data, loadMore, loadingMore, hasMore }) {
  const [expanded, setExpanded] = useState(null);
  const toggle = (id) => setExpanded(expanded === id ? null : id);

  const COL = '1.4fr 0.8fr 1.2fr 1.2fr 1.2fr 1.2fr 0.4fr';

  return (
    <div>
      <div style={{
        display: 'grid', gridTemplateColumns: COL,
        padding: '16px 24px', background: C.surface,
        borderBottom: `1px solid ${C.borderLight}`, gap: 12,
      }}>
        <Th>Trade ID · Run</Th>
        <Th>Action</Th>
        <Th right>Price (THB)</Th>
        <Th right>Amount</Th>
        <Th right>P&amp;L</Th>
        <Th center>Portfolio Flow</Th>
        <Th />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {data.map((t) => {
          const open = expanded === t.id;
          const hasPnl = t.pnl_thb !== null;
          const profit = hasPnl && t.pnl_thb > 0;
          const cashDelta = (t.cash_after - t.cash_before).toFixed(0);
          const goldDelta = (t.gold_after - t.gold_before).toFixed(4);

          return (
            <div key={t.id}>
              <div
                onClick={() => toggle(t.id)}
                style={{
                  display: 'grid', gridTemplateColumns: COL,
                  padding: '16px 24px', gap: 12, alignItems: 'center',
                  borderBottom: `1px solid ${C.borderLight}`,
                  cursor: 'pointer',
                  background: open ? C.bg : 'white',
                  transition: 'all 0.2s ease',
                  borderLeft: hasPnl ? `4px solid ${profit ? C.green : C.red}` : `4px solid ${C.blue}`,
                }}
                onMouseEnter={e => { if (!open) e.currentTarget.style.background = '#FCFDFE'; }}
                onMouseLeave={e => { if (!open) e.currentTarget.style.background = 'white'; }}
              >
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.textDark }}>#TXN-{t.id}</div>
                  <Sub>RUN #{t.run_id} · {t.executed_at?.slice(0, 19)?.replace('T', ' ')}</Sub>
                </div>

                <div><ActionBadge action={t.action} /></div>

                <div style={{ textAlign: 'right' }}>
                  <Cell right mono>{t.price_thb?.toLocaleString()} ฿</Cell>
                  <Sub>{t.gold_grams?.toFixed(4)} g</Sub>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <Cell right mono>{t.amount_thb?.toLocaleString()} ฿</Cell>
                  <Sub>Basis: {t.cost_basis_thb?.toLocaleString()}</Sub>
                </div>

                <div style={{ textAlign: 'right' }}>
                  {hasPnl ? (
                    <>
                      <div style={{ fontSize: 15, fontWeight: 800,
                        color: profit ? C.green : C.red,
                        fontVariantNumeric: 'tabular-nums' }}>
                        {profit ? '+' : ''}{t.pnl_thb?.toLocaleString()} ฿
                      </div>
                      <div style={{ fontSize: 11, color: profit ? C.green : C.red, fontWeight: 600, marginTop: 2 }}>
                        {(t.pnl_pct * 100).toFixed(2)}%
                      </div>
                    </>
                  ) : (
                    <span style={{ fontSize: 10, fontWeight: 700, color: C.brandPurple,
                      background: '#F3E8FF', borderRadius: '8px', padding: '4px 10px', letterSpacing: '0.05em' }}>HOLDING</span>
                  )}
                </div>

                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: C.textDark }}>
                    Cash <span style={{ color: Number(cashDelta) > 0 ? C.green : C.red, fontWeight: 700 }}>
                      {Number(cashDelta) > 0 ? '+' : ''}{Number(cashDelta).toLocaleString()}
                    </span>
                  </div>
                  <div style={{ fontSize: 11, fontFamily: "'JetBrains Mono', monospace", color: C.muted, marginTop: 4 }}>
                    Gold <span style={{ color: Number(goldDelta) > 0 ? C.green : C.red, fontWeight: 700 }}>
                      {Number(goldDelta) > 0 ? '+' : ''}{goldDelta}g
                    </span>
                  </div>
                </div>

                <div style={{ textAlign: 'center', color: C.brandPurple, fontSize: 18,
                  transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.3s ease', fontWeight: 300 }}>›</div>
              </div>

              {open && (
                <div style={{
                  background: C.bg,
                  padding: '20px 24px',
                  borderBottom: `1px solid ${C.borderLight}`,
                  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 16,
                }}>
                  <DetailItem label="Cash Before → After"
                    value={`${t.cash_before?.toLocaleString()} → ${t.cash_after?.toLocaleString()} ฿`} mono />
                  <DetailItem label="Gold Before → After"
                    value={`${t.gold_before?.toFixed(4)} → ${t.gold_after?.toFixed(4)} g`} mono />
                  <DetailItem label="AI Signal" value={`${t.run_signal} (${(t.run_confidence*100).toFixed(0)}%)`} />
                  <DetailItem label="Provider" value={t.run_provider} mono />
                  <div style={{ gridColumn: '1 / -1', background: 'white', padding: '16px', borderRadius: '12px', border: `1px solid ${C.borderLight}` }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: C.brandPurple, letterSpacing: '0.05em',
                      textTransform: 'uppercase', marginBottom: 8 }}>AI Rationale</div>
                    <div style={{ fontSize: 13, color: C.text, lineHeight: 1.6 }}>{t.run_rationale}</div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <LoadMoreBtn onClick={loadMore} loading={loadingMore} hasMore={hasMore} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// LLM LOGS TAB
// ─────────────────────────────────────────────────────────────────────────────
function LogsTab({ data, loadMore, loadingMore, hasMore }) {
  const [expanded, setExpanded] = useState(null);
  const toggle = (id) => setExpanded(expanded === id ? null : id);

  const COL = '1.4fr 1fr 0.8fr 0.8fr 1fr 0.8fr 0.4fr';

  return (
    <div>
      <div style={{
        display: 'grid', gridTemplateColumns: COL,
        padding: '16px 24px', background: C.surface,
        borderBottom: `1px solid ${C.borderLight}`, gap: 12,
      }}>
        <Th>Log ID · Run</Th>
        <Th>Step Type</Th>
        <Th center>Signal</Th>
        <Th center>Confidence</Th>
        <Th center>Token Usage</Th>
        <Th right>Latency</Th>
        <Th />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {data.map((l) => {
          const open = expanded === l.id;
          return (
            <div key={l.id}>
              <div
                onClick={() => toggle(l.id)}
                style={{
                  display: 'grid', gridTemplateColumns: COL,
                  padding: '16px 24px', gap: 12, alignItems: 'center',
                  borderBottom: `1px solid ${C.borderLight}`,
                  cursor: 'pointer',
                  background: open ? C.bg : 'white',
                  transition: 'all 0.2s ease',
                }}
                onMouseEnter={e => { if (!open) e.currentTarget.style.background = '#FCFDFE'; }}
                onMouseLeave={e => { if (!open) e.currentTarget.style.background = 'white'; }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: C.textDark }}>#{l.id}</span>
                    {l.is_fallback && (
                      <span style={{ fontSize: 9, background: C.goldLight, color: '#92400E',
                        padding: '2px 6px', borderRadius: '6px',
                        fontWeight: 700, textTransform: 'uppercase' }}>fallback</span>
                    )}
                  </div>
                  <Sub>RUN #{l.run_id} · iter {l.iteration}</Sub>
                </div>

                <div><StepBadge type={l.step_type} /></div>

                <div style={{ textAlign: 'center' }}>
                  <SignalBadge signal={l.signal === '—' ? 'HOLD' : l.signal} />
                </div>

                {/* แก้จาก value={l.confidence} เป็น value={l.confidence * 100} */}
                <div><ConfBar value={l.confidence * 100} /></div>

                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 12, fontFamily: "'JetBrains Mono', monospace", color: C.textDark, fontWeight: 600 }}>
                    {l.token_total?.toLocaleString()} tok
                  </div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>
                    ↑{l.token_input} ↓{l.token_output}
                  </div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <Cell right mono
                    color={l.elapsed_ms > 10000 ? C.red : l.elapsed_ms > 5000 ? '#F59E0B' : C.green}>
                    {l.elapsed_ms?.toLocaleString()}ms
                  </Cell>
                  <Sub>{l.provider?.split(':').pop()?.slice(0, 18)}</Sub>
                </div>

                <div style={{ textAlign: 'center', color: C.brandPurple, fontSize: 18,
                  transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.3s ease', fontWeight: 300 }}>›</div>
              </div>

              {open && (
                <div style={{
                  background: C.bg,
                  padding: '20px 24px',
                  borderBottom: `1px solid ${C.borderLight}`,
                  display: 'flex', flexDirection: 'column', gap: 16,
                }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
                    <DetailItem label="Entry Price" value={l.entry_price ? `${l.entry_price.toLocaleString()} ฿` : '—'} mono />
                    <DetailItem label="Stop Loss"   value={l.stop_loss   ? `${l.stop_loss.toLocaleString()} ฿`   : '—'} mono color={C.red} />
                    <DetailItem label="Take Profit" value={l.take_profit ? `${l.take_profit.toLocaleString()} ฿` : '—'} mono color={C.green} />
                    <DetailItem label="Tools Used"  value={`${l.tool_calls_used} calls · ${l.iterations_used} iter`} />
                  </div>
                  {l.rationale && (
                     <div style={{ background: 'white', padding: '16px', borderRadius: '12px', border: `1px solid ${C.borderLight}` }}>
                       <div style={{ fontSize: 10, fontWeight: 700, color: C.brandPurple, letterSpacing: '0.05em',
                         textTransform: 'uppercase', marginBottom: 8 }}>Rationale Output</div>
                       <div style={{ fontSize: 13, color: C.text, lineHeight: 1.6, fontFamily: "'JetBrains Mono', monospace", whiteSpace: 'pre-wrap' }}>
                         {l.rationale}
                       </div>
                     </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <LoadMoreBtn onClick={loadMore} loading={loadingMore} hasMore={hasMore} />
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// SUMMARY CARDS (Dashboard style)
// ─────────────────────────────────────────────────────────────────────────────
function SummaryCards({ summary }) {
  if (!summary) return null;
  const { total_runs, total_trades, realized_pnl, win_rate,
    avg_exec_ms, buy_count, sell_count, hold_count } = summary;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 20, marginBottom: 32 }}>

      {/* NET PNL Card */}
      <div style={{ ...cardStyle, padding: '24px' }}>
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ width: 32, height: 32, borderRadius: '8px', background: C.greenBg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: C.green, fontSize: 16, fontWeight: 'bold' }}>↗</span>
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, letterSpacing: '0.05em', textTransform: 'uppercase', alignSelf: 'center' }}>
            Net PNL
          </div>
        </div>
        <div style={{ fontSize: 28, fontWeight: 800, color: C.textDark, fontVariantNumeric: 'tabular-nums' }}>
          {realized_pnl >= 0 ? '+' : ''}{realized_pnl?.toLocaleString()} <span style={{ fontSize: 14, color: C.green }}>THB</span>
        </div>
      </div>

      {/* WIN RATE Card */}
      <div style={{ ...cardStyle, padding: '24px' }}>
         <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ width: 32, height: 32, borderRadius: '8px', background: '#F3E8FF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: '#9333EA', fontSize: 16, fontWeight: 'bold' }}>◎</span>
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, letterSpacing: '0.05em', textTransform: 'uppercase', alignSelf: 'center' }}>
            Win Rate
          </div>
        </div>
        <div style={{ fontSize: 28, fontWeight: 800, color: C.textDark }}>
          {win_rate?.toFixed(2)} <span style={{ fontSize: 16, color: '#9333EA' }}>%</span>
        </div>
      </div>

      {/* TOTAL RUNS Card */}
      <div style={{ ...cardStyle, padding: '24px' }}>
        <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ width: 32, height: 32, borderRadius: '8px', background: C.blueBg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: C.blue, fontSize: 16, fontWeight: 'bold' }}>⚡</span>
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, letterSpacing: '0.05em', textTransform: 'uppercase', alignSelf: 'center' }}>
            Total Runs
          </div>
        </div>
        <div style={{ fontSize: 28, fontWeight: 800, color: C.textDark }}>
          {total_runs?.toLocaleString()}
        </div>
        <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>avg {avg_exec_ms?.toFixed(0)}ms / run</div>
      </div>

      {/* EXECUTIONS Card */}
      <div style={{ ...cardStyle, padding: '24px' }}>
         <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <div style={{ width: 32, height: 32, borderRadius: '8px', background: C.goldBg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <span style={{ color: '#D97706', fontSize: 16, fontWeight: 'bold' }}>⟷</span>
          </div>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, letterSpacing: '0.05em', textTransform: 'uppercase', alignSelf: 'center' }}>
            Executions
          </div>
        </div>
        <div style={{ fontSize: 28, fontWeight: 800, color: C.textDark }}>
          {total_trades}
        </div>
      </div>

      {/* SIGNAL MIX Card */}
      <div style={{ ...cardStyle, padding: '24px' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, letterSpacing: '0.05em',
          textTransform: 'uppercase', marginBottom: 16 }}>Signal Mix</div>
        {[
          { label: 'BUY',  count: buy_count,  color: C.green  },
          { label: 'SELL', count: sell_count, color: C.red }, 
          { label: 'HOLD', count: hold_count, color: '#D97706'  }, // Changed to yellow/gold
        ].map(({ label, count, color }) => {
          const total = (buy_count || 0) + (sell_count || 0) + (hold_count || 0);
          const pct = total > 0 ? (count / total) * 100 : 0;
          return (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color, width: 32, letterSpacing: '0.05em' }}>{label}</div>
              <div style={{ flex: 1, height: 4, background: C.grayBg, borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
              </div>
              <div style={{ fontSize: 11, color: C.muted, width: 28, textAlign: 'right', fontWeight: 600 }}>{count}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────
export default function HistorySection() {
  const [tab, setTab] = useState('RUNS');
  const [summary, setSummary] = useState(null);
  const [summaryError, setSummaryError] = useState(null);

  const [runs,       setRuns]       = useState([]);
  const [trades,     setTrades]     = useState([]);
  const [logs,       setLogs]       = useState([]);

  const [loading,    setLoading]    = useState({ RUNS: false, TRADES: false, LOGS: false });
  const [loadMore,   setLoadMore]   = useState({ RUNS: false, TRADES: false, LOGS: false });
  const [offsets,    setOffsets]    = useState({ RUNS: 0,     TRADES: 0,     LOGS: 0     });
  const [hasMore,    setHasMore]    = useState({ RUNS: true,  TRADES: true,  LOGS: true  });
  const [errors,     setErrors]     = useState({ RUNS: null,  TRADES: null,  LOGS: null  });

  const [filterSignal, setFilterSignal] = useState('');
  const [filterStep,   setFilterStep]   = useState('');

  const initialized = useRef({ RUNS: false, TRADES: false, LOGS: false });

  useEffect(() => {
    apiFetch('/api/history/summary')
      .then(setSummary)
      .catch(e => setSummaryError(e.message));
  }, []);

  const fetchTab = useCallback(async (tabKey, append = false) => {
    const currentOffset = append ? offsets[tabKey] : 0;

    if (append) {
      setLoadMore(p => ({ ...p, [tabKey]: true }));
    } else {
      setLoading(p => ({ ...p, [tabKey]: true }));
      setErrors(p => ({ ...p, [tabKey]: null }));
    }

    try {
      let url = '';
      if (tabKey === 'RUNS') {
        url = `/api/history/runs?limit=${PAGE_SIZE}&offset=${currentOffset}`;
        if (filterSignal) url += `&signal=${filterSignal}`;
      } else if (tabKey === 'TRADES') {
        url = `/api/history/trades?limit=${PAGE_SIZE}&offset=${currentOffset}`;
      } else {
        url = `/api/history/logs?limit=${PAGE_SIZE}&offset=${currentOffset}`;
        if (filterStep) url += `&step_type=${filterStep}`;
      }

      const data = await apiFetch(url);
      const newOffset = currentOffset + data.length;

      if (tabKey === 'RUNS')   setRuns(p   => append ? [...p, ...data] : data);
      if (tabKey === 'TRADES') setTrades(p => append ? [...p, ...data] : data);
      if (tabKey === 'LOGS')   setLogs(p   => append ? [...p, ...data] : data);

      setOffsets(p => ({ ...p, [tabKey]: newOffset }));
      setHasMore(p => ({ ...p, [tabKey]: data.length === PAGE_SIZE }));
    } catch (e) {
      setErrors(p => ({ ...p, [tabKey]: e.message }));
    } finally {
      setLoading(p  => ({ ...p, [tabKey]: false }));
      setLoadMore(p => ({ ...p, [tabKey]: false }));
    }
  }, [offsets, filterSignal, filterStep]);

  useEffect(() => {
    if (!initialized.current[tab]) {
      initialized.current[tab] = true;
      fetchTab(tab);
    }
  }, [tab, fetchTab]);

  useEffect(() => {
    initialized.current['RUNS'] = true;
    setOffsets(p => ({ ...p, RUNS: 0 }));
    setHasMore(p => ({ ...p, RUNS: true }));
    fetchTab('RUNS');
  }, [filterSignal]);

  useEffect(() => {
    initialized.current['LOGS'] = true;
    setOffsets(p => ({ ...p, LOGS: 0 }));
    setHasMore(p => ({ ...p, LOGS: true }));
    fetchTab('LOGS');
  }, [filterStep]);

  const TABS = [
    { key: 'RUNS',   label: 'Agent Runs',    endpoint: '/api/history/runs',   count: summary?.total_runs,   accent: C.gold   },
    { key: 'TRADES', label: 'Executions',    endpoint: '/api/history/trades', count: summary?.total_trades, accent: C.green  },
    { key: 'LOGS',   label: 'LLM Logs',      endpoint: '/api/history/logs',   count: null,                  accent: C.brandPurple },
  ];

  const curData    = { RUNS: runs,   TRADES: trades,     LOGS: logs     };
  const curLoading = { RUNS: loading.RUNS, TRADES: loading.TRADES, LOGS: loading.LOGS };
  const curError   = { RUNS: errors.RUNS,  TRADES: errors.TRADES,  LOGS: errors.LOGS  };
  const curHasMore = { RUNS: hasMore.RUNS, TRADES: hasMore.TRADES, LOGS: hasMore.LOGS };
  const curLM      = { RUNS: loadMore.RUNS,TRADES: loadMore.TRADES,LOGS: loadMore.LOGS };

  const isLoading = curLoading[tab];
  const isError   = curError[tab];

  return (
    // 1. เอา padding ออกจากกล่องนอกสุด เพื่อให้ Header กางเต็มจอ
    <div style={{ minHeight: '100vh', background: C.bg,
      fontFamily: "'Inter', 'IBM Plex Sans', system-ui, sans-serif" }}>

      {/* 2. ใส่ OverviewHeader ไว้บนสุด */}
      <OverviewHeader />

      {/* 3. สร้าง div มารับ padding เดิม เพื่อให้เนื้อหาข้างในเว้นระยะสวยงามเหมือนเดิม */}
      <div style={{ padding: '40px 48px' }}>
        
        {/* ── Page header (Local context) ── */}
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 32 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div style={{ width: 24, height: 3, background: C.gold, borderRadius: 2 }} />
              <span style={{ fontSize: 11, fontWeight: 700, color: C.brandPurple,
                letterSpacing: '0.15em', textTransform: 'uppercase' }}>
                System Archive
              </span>
            </div>
            <h2 style={{ fontSize: 32, fontWeight: 800, color: C.textDark, margin: 0, letterSpacing: '-0.02em' }}>
              Historical Records
            </h2>
          </div>

          <button
            onClick={() => {
              initialized.current = { RUNS: false, TRADES: false, LOGS: false };
              setSummary(null);
              apiFetch('/api/history/summary').then(setSummary).catch(() => {});
              setRuns([]); setTrades([]); setLogs([]);
              setOffsets({ RUNS: 0, TRADES: 0, LOGS: 0 });
              setHasMore({ RUNS: true, TRADES: true, LOGS: true });
              fetchTab(tab);
            }}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 20px',
              borderRadius: '12px', border: `1px solid ${C.borderLight}`, background: 'white',
              fontSize: 13, fontWeight: 600, color: C.brandPurple, cursor: 'pointer', // changed from C.textDark
              boxShadow: '0 2px 5px rgba(0,0,0,0.02)' }}>
            <span style={{ color: C.brandPurple, fontSize: 16 }}>↻</span> Refresh Data
          </button>
        </div>

        {/* ── Summary cards ── */}
        {summaryError ? (
          <div style={{ padding: '16px 20px', background: C.redBg, border: `1px solid #FECACA`,
            borderRadius: '12px', fontSize: 13, color: C.red, marginBottom: 32, fontWeight: 500 }}>
            ⚠ Failed to load summary: {summaryError}
          </div>
        ) : (
          <SummaryCards summary={summary} />
        )}

        {/* ── Main Data Panel ── */}
        <div style={{ ...cardStyle }}>
          
          {/* Header inside table card */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '20px 24px', borderBottom: `1px solid ${C.borderLight}`, background: '#FCFDFE' }}>
            
            <div style={{ display: 'flex', gap: 12 }}>
              {TABS.map(({ key, label, count, accent }) => {
                const active = tab === key;
                return (
                  <button key={key} onClick={() => setTab(key)} style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '8px 16px', borderRadius: '100px', cursor: 'pointer',
                    fontSize: 13, fontWeight: active ? 700 : 600, border: 'none',
                    color: active ? 'white' : C.gray,
                    background: active ? C.brandPurple : 'transparent', // changed from C.brandDark
                    transition: 'all 0.2s',
                  }}>
                    {label}
                    {count != null && (
                      <span style={{ fontSize: 11, background: active ? 'rgba(255,255,255,0.2)' : C.grayBg,
                        color: active ? 'white' : C.text, padding: '2px 8px',
                        borderRadius: '100px' }}>
                        {count?.toLocaleString()}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            <div style={{ display: 'flex', gap: 12 }}>
              {tab === 'RUNS' && (
                <select value={filterSignal} onChange={e => setFilterSignal(e.target.value)}
                  style={{ fontSize: 12, padding: '8px 16px', borderRadius: '8px',
                    border: `1px solid ${C.borderLight}`, color: C.textDark, fontWeight: 600,
                    background: 'white', cursor: 'pointer', outline: 'none' }}>
                  <option value="">All Signals</option>
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                  <option value="HOLD">HOLD</option>
                </select>
              )}
              {tab === 'LOGS' && (
                <select value={filterStep} onChange={e => setFilterStep(e.target.value)}
                  style={{ fontSize: 12, padding: '8px 16px', borderRadius: '8px',
                    border: `1px solid ${C.borderLight}`, color: C.textDark, fontWeight: 600,
                    background: 'white', cursor: 'pointer', outline: 'none' }}>
                  <option value="">All Steps</option>
                  <option value="THOUGHT_FINAL">THOUGHT_FINAL</option>
                  <option value="TOOL_CALL">TOOL_CALL</option>
                  <option value="THOUGHT">THOUGHT</option>
                </select>
              )}
            </div>
          </div>

          {/* Content Area */}
          <div style={{ minHeight: 400 }}>
            {isLoading ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                height: 300, gap: 12, color: C.brandPurple }}>
                <span style={{ fontSize: 24, animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span>
                <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '0.1em',
                  textTransform: 'uppercase' }}>Loading Records...</span>
              </div>
            ) : isError ? (
              <div style={{ padding: '32px' }}>
                <div style={{ background: C.redBg, border: `1px solid #FECACA`,
                  borderRadius: '12px', padding: '20px', fontSize: 13, color: C.red, fontWeight: 500 }}>
                  ⚠ Error fetching data: {isError}
                  <button onClick={() => fetchTab(tab)} style={{
                    marginLeft: 16, fontSize: 12, fontWeight: 700,
                    color: C.red, background: 'transparent', border: 'none',
                    cursor: 'pointer', textDecoration: 'underline' }}>Try Again</button>
                </div>
              </div>
            ) : curData[tab].length === 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                height: 250, color: C.muted, fontSize: 13, fontWeight: 600,
                letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                No records found
              </div>
            ) : tab === 'RUNS' ? (
              <RunsTab data={curData.RUNS} loadMore={() => fetchTab('RUNS', true)} loadingMore={curLM.RUNS} hasMore={curHasMore.RUNS} />
            ) : tab === 'TRADES' ? (
              <TradesTab data={curData.TRADES} loadMore={() => fetchTab('TRADES', true)} loadingMore={curLM.TRADES} hasMore={curHasMore.TRADES} />
            ) : (
              <LogsTab data={curData.LOGS} loadMore={() => fetchTab('LOGS', true)} loadingMore={curLM.LOGS} hasMore={curHasMore.LOGS} />
            )}
          </div>
        </div>

      </div> {/* <-- 4. ปิด div ที่ครอบ padding ตรงนี้ */}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
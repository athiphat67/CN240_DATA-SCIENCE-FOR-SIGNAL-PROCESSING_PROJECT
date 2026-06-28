import React, { useState } from 'react';
import { Brain, Search, Database, Zap, ChevronDown, ChevronUp, Clock, Crosshair, ShieldX } from 'lucide-react';

export type SignalType = 'BUY' | 'HOLD' | 'SELL';

// 1. Export Interface ออกไปให้ SignalsSection ใช้ด้วย
export interface SignalLog {
  id: number;
  logged_at: string;
  interval_tf: string;
  entry_price: number | null;
  take_profit: number | null;
  stop_loss: number | null;
  signal: SignalType | null;
  confidence: number;
  rationale?: string;
  trace_json?: string;
}

// 2. ปรับ Props ให้รับข้อมูลมาจาก SignalsSection แทน
interface SignalMasterTableProps {
  signals: SignalLog[];
  isLoading: boolean;
}

const SignalPill = ({ signal }: { signal: SignalType }) => {
  const styles: Record<SignalType, string> = {
    BUY: 'bg-emerald-100/80 text-emerald-700 border-emerald-200',
    HOLD: 'bg-amber-100/80 text-amber-700 border-amber-200',
    SELL: 'bg-rose-100/80 text-rose-700 border-rose-200',
  };
  
  return (
    <span className={`text-[11px] font-black px-3 py-1 rounded-full border tracking-wider flex justify-center items-center ${styles[signal]}`}>
      {signal}
    </span>
  );
};

export const SignalMasterTable = ({ signals, isLoading }: SignalMasterTableProps) => {
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const toggleTrace = (id: number) => {
    setExpandedId(expandedId === id ? null : id);
  };

  const formatDate = (isoString: string) => {
    if (!isoString) return 'Unknown';
    const date = new Date(isoString);
    return date.toLocaleString('en-GB', {
      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
    }).replace(',', '');
  };

  const renderTraceSteps = (traceJson?: string) => {
    if (!traceJson) return <p className="text-xs text-gray-400">No trace data available for this signal.</p>;

    try {
      const steps = JSON.parse(traceJson);
      return steps.map((step: any, idx: number) => (
        <div key={idx} className="flex gap-4">
          <div className="flex flex-col items-center">
            <div className="w-7 h-7 rounded-full bg-white border border-gray-100 shadow-sm flex items-center justify-center text-[#824199] z-10">
              {step.step === 'TOOL_EXECUTION' ? <Search size={14} /> : step.step.includes('THOUGHT') ? <Brain size={14} /> : <Zap size={14} />}
            </div>
            {idx !== steps.length - 1 && <div className="w-0.5 h-full bg-gray-200 -mt-1 mb-1" />}
          </div>
          <div className="pb-4 pt-1">
            <h5 className="text-[10px] font-black text-gray-900 uppercase tracking-tighter">
              {step.step === 'TOOL_EXECUTION' ? `Tool: ${step.tool_name}` : step.step}
            </h5>
            <p className="text-[11px] text-gray-500 font-medium mt-0.5 line-clamp-2">
              {step.response?.thought || step.observation?.error || "Processing iteration..."}
            </p>
          </div>
        </div>
      ));
    } catch (e) {
      return <p className="text-xs text-rose-400">Error parsing trace logs.</p>;
    }
  };

  const gridColumns = "grid grid-cols-[40px_1.5fr_0.5fr_1fr_2fr_1.5fr_120px] gap-4";

  return (
    <div className="bg-white rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-gray-100 overflow-hidden font-sans">

      {/* Header ของตาราง (เอาส่วน Top Bar ซ้ำซ้อนออกแล้ว) */}
      <div className={`${gridColumns} bg-gray-50/80 text-[10px] font-black text-gray-400 uppercase tracking-widest p-4 px-6 border-b border-gray-100 items-center`}>
        <div className="flex justify-center"><input type="checkbox" className="rounded-md border-gray-300 text-[#824199]" /></div>
        <span>Date & ID</span>
        <span className="text-center">TF</span>
        <span className="text-center">Action</span>
        <span className="text-center">Price Targets</span>
        <span className="text-center">Confidence</span>
        <span className="text-right">Trace</span>
      </div>

      {/* Table Body */}
      <div className="divide-y divide-gray-50/80">
        {isLoading ? (
          <div className="py-16 flex justify-center items-center">
            <span className="text-sm font-medium text-gray-400 animate-pulse flex items-center gap-2">
              <Brain className="animate-spin text-purple-400" size={16} /> Loading intelligence data...
            </span>
          </div>
        ) : signals.length === 0 ? (
          <div className="py-16 flex justify-center items-center">
            <span className="text-sm font-medium text-gray-400">No intelligence history found.</span>
          </div>
        ) : (
          signals.map((row) => {
            const safeSignal = row.signal || 'HOLD';
            const confPercent = row.confidence <= 1 ? Math.round(row.confidence * 100) : row.confidence;
            const displayRationale = row.rationale || `Algorithm executed quantitative analysis on ${row.interval_tf} timeframe. Multiple indicators triggered a ${safeSignal} bias.`;

            return (
              <React.Fragment key={row.id}>
                {/* Main Row */}
                <div className={`${gridColumns} items-center p-4 px-6 transition-all ${expandedId === row.id ? 'bg-purple-50/30' : 'hover:bg-gray-50/50'}`}>
                  
                  {/* Checkbox */}
                  <div className="flex justify-center">
                    <input type="checkbox" className="rounded-md border-gray-300 text-[#824199]" />
                  </div>

                  {/* Date & ID */}
                  <div>
                    <p className="text-[13px] font-bold text-gray-900 flex items-center gap-1.5">
                      <Clock size={12} className="text-gray-400" /> {formatDate(row.logged_at)}
                    </p>
                    <p className="text-[10px] text-gray-400 font-mono mt-0.5">#{row.id}</p>
                  </div>

                  {/* Timeframe */}
                  <div className="flex justify-center">
                    <span className="bg-white text-gray-500 text-[10px] font-bold px-2.5 py-1 rounded-lg border border-gray-100 shadow-sm">{row.interval_tf || '-'}</span>
                  </div>

                  {/* Signal Pill */}
                  <div className="flex justify-center">
                    <SignalPill signal={safeSignal} />
                  </div>

                  {/* Price Targets */}
                  <div className="flex flex-col items-center gap-1">
                    <div className="flex items-center gap-2 text-sm font-black text-gray-900">
                      {row.entry_price ? row.entry_price.toLocaleString('en-US', { minimumFractionDigits: 2 }) : '—'} 
                      {row.entry_price && <span className="text-[10px] text-gray-400 font-bold">ENTRY</span>}
                    </div>
                    {safeSignal !== 'HOLD' && (row.take_profit || row.stop_loss) && (
                      <div className="flex items-center justify-center gap-3 text-[10px] font-bold">
                        {row.take_profit && (
                            <span className="flex items-center gap-1 text-emerald-600">
                            <Crosshair size={10}/> 
                            {row.take_profit.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                        )}
                        {row.stop_loss && (
                            <span className="flex items-center gap-1 text-rose-500">
                            <ShieldX size={10}/> 
                            {row.stop_loss.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                            </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Confidence Bar */}
                  <div className="flex justify-center items-center gap-3">
                    <div className="w-16 h-2 bg-gray-100 rounded-full overflow-hidden shadow-inner flex-shrink-0">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-[#824199] to-[#c084fc]"
                        style={{ width: `${confPercent}%` }}
                      />
                    </div>
                    <span className="text-[11px] font-black text-gray-700 w-8">{confPercent}%</span>
                  </div>

                  {/* ปุ่มเปิด Trace */}
                  <div className="text-right flex justify-end">
                    <button
                      onClick={() => toggleTrace(row.id)}
                      className={`inline-flex items-center gap-1 text-[10px] font-black uppercase tracking-widest transition-all px-3 py-2 rounded-xl border ${expandedId === row.id
                        ? 'bg-[#824199] text-white border-[#824199] shadow-md shadow-purple-200'
                        : 'text-gray-500 hover:text-[#824199] bg-white border-gray-200 hover:border-purple-200'
                        }`}
                    >
                      {expandedId === row.id ? 'Close' : 'Trace'}
                      {expandedId === row.id ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                  </div>
                </div>

                {/* Sub-column (Trace Log) */}
                {expandedId === row.id && (
                  <div className="bg-gray-50/80 border-x-4 border-[#824199]/20 shadow-inner animate-in fade-in slide-in-from-top-2 duration-300">
                    <div className="p-8 grid grid-cols-12 gap-8">

                      {/* ฝั่งซ้าย: Rationale */}
                      <div className="col-span-12 md:col-span-5 lg:col-span-4">
                        <div className="bg-[#13071a] p-6 rounded-[24px] text-white relative overflow-hidden h-full shadow-lg">
                          <Brain className="absolute -right-4 -bottom-4 opacity-10" size={80} />
                          <p className="text-[10px] font-bold text-purple-300 uppercase tracking-[0.2em] mb-3">Final Agent Rationale</p>
                          <p className="text-sm italic font-medium leading-relaxed relative z-10">"{displayRationale}"</p>
                        </div>
                      </div>

                      {/* ฝั่งขวา: Execution Steps */}
                      <div className="col-span-12 md:col-span-7 lg:col-span-8 space-y-5">
                        <h4 className="text-[10px] font-black text-gray-500 uppercase tracking-[0.2em] mb-4">Execution Traces</h4>
                        
                        <div className="space-y-0">
                           <TraceItem icon={<Search size={14} />} title="Market Scan" desc={`Ingesting multi-source market data on ${row.interval_tf || 'default'} timeframe.`} />
                           <TraceItem icon={<Database size={14} />} title="Pattern Recognition" desc="Analyzing current trend, volume support, and historical resistance." />
                           <TraceItem icon={<Brain size={14} />} title="Inference" desc={`Quantitative conditions met. Confidence parameter at ${confPercent}%.`} />
                           {renderTraceSteps(row.trace_json)}
                        </div>
                      </div>

                    </div>
                  </div>
                )}
              </React.Fragment>
            );
          })
        )}
      </div>
    </div>
  );
};

// Component สำหรับ Timeline ในส่วนของ Trace
const TraceItem = ({ icon, title, desc, isLast }: { icon: React.ReactNode, title: string, desc: string, isLast?: boolean }) => (
  <div className="flex gap-4">
    <div className="flex flex-col items-center">
      <div className="w-7 h-7 rounded-full bg-white border border-gray-100 shadow-sm flex items-center justify-center text-gray-400 z-10">
        {icon}
      </div>
      {!isLast && <div className="w-0.5 h-full bg-gray-200 -mt-1 mb-1" />}
    </div>
    <div className="pb-4 pt-1">
      <h5 className="text-[10px] font-black text-gray-900 uppercase tracking-tighter">{title}</h5>
      <p className="text-[11px] text-gray-500 font-medium mt-0.5">{desc}</p>
    </div>
  </div>
);
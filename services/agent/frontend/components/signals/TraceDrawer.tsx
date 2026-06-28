import React from 'react';
import { X, Brain, Zap, Search, Database } from 'lucide-react';

export const TraceDrawer = ({ isOpen, onClose, signal }: any) => {
  if (!isOpen || !signal) return null;

  return (
    <div className="fixed inset-0 z-[1000] overflow-hidden">
      {/* Overlay สำหรับปิดเมื่อคลิกด้านนอก */}
      <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" onClick={onClose} />
      
      <div className="absolute inset-y-0 right-0 max-w-xl w-full bg-white shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
        {/* Header ของ Drawer */}
        <div className="p-6 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-black text-gray-900">Intelligence Trace</h3>
            <p className="text-xs text-gray-400 font-mono">Trace ID: #{signal.id}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-gray-100 rounded-full transition-colors">
            <X size={20} className="text-gray-400" />
          </button>
        </div>

        {/* Content: โชว์ ReAct Loop Log */}
        <div className="flex-1 overflow-y-auto p-6 space-y-8">
          <div className="bg-[#1a0a24] p-6 rounded-3xl text-white relative overflow-hidden">
             <div className="absolute top-0 right-0 p-4 opacity-10"><Brain size={60} /></div>
             <p className="text-[10px] font-bold text-purple-300 uppercase tracking-widest mb-2">Final Rationale</p>
             <p className="text-sm italic font-medium leading-relaxed">"{signal.rationale}"</p>
          </div>

          <div className="space-y-6">
            <h4 className="text-[11px] font-bold text-gray-400 uppercase tracking-[0.2em] mb-4">ReAct Process Log</h4>
            {/* จำลองขั้นตอนความคิด AI */}
            <TraceStep icon={<Brain size={14}/>} title="Thought" desc="Analyzing 4H timeframe for MACD crossover and volume confirmation." />
            <TraceStep icon={<Search size={14}/>} title="Action: get_technical_indicators" desc="Retrieving RSI, MACD, and Bollinger Bands data." />
            <TraceStep icon={<Database size={14}/>} title="Observation" desc="RSI at 42.5 (Neutral), MACD line crossing above Signal line." />
            <TraceStep icon={<Zap size={14} className="text-emerald-500"/>} title="Final Decision: BUY" desc="Entry point confirmed at 41,200 THB/g." />
          </div>
        </div>
      </div>
    </div>
  );
};

const TraceStep = ({ icon, title, desc }: any) => (
  <div className="relative pl-8 border-l-2 border-gray-50 pb-6 last:pb-0 last:border-0">
    <div className="absolute -left-[13px] top-0 w-6 h-6 rounded-full bg-white border-2 border-gray-100 flex items-center justify-center text-gray-400 shadow-sm">
      {icon}
    </div>
    <div>
      <h5 className="text-[11px] font-black text-gray-900 uppercase mb-1">{title}</h5>
      <p className="text-xs text-gray-500 leading-relaxed font-medium">{desc}</p>
    </div>
  </div>
);
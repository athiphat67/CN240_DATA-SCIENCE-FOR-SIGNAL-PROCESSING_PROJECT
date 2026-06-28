import React, { useState } from 'react';
import { Bot, AlertOctagon, TrendingDown, Crosshair, BrainCircuit, Activity, Cpu } from 'lucide-react';

export const AgentSettings = () => {
  const [autoSignal, setAutoSignal] = useState(true);
  const [trailingStop, setTrailingStop] = useState(true);
  const [provider, setProvider] = useState('openai');
  const [timeframe, setTimeframe] = useState('1h');
  const [riskLevel, setRiskLevel] = useState('Moderate');

  return (
    <div className="flex flex-col gap-6">
      
      {/* 1. Master Toggle: Auto-Signal Alerts */}
      <div className="bg-white p-8 rounded-[24px] border border-gray-100 shadow-[0_4px_20px_rgba(0,0,0,0.02)] flex flex-col sm:flex-row sm:items-center justify-between gap-6">
        <div>
          <h3 className="text-lg font-black text-gray-900 flex items-center gap-2 mb-1.5">
            <Bot size={20} className="text-[#824199]" /> Real-time Signal Alerts
          </h3>
          <p className="text-sm text-gray-500 font-medium max-w-md leading-relaxed">
            อนุญาตให้ AI Agent วิเคราะห์และส่งการแจ้งเตือนสัญญาณ (BUY/SELL/HOLD) เข้าสู่ระบบแบบเรียลไทม์ตามระดับความมั่นใจ
          </p>
        </div>
        <ToggleSwitch enabled={autoSignal} onChange={() => setAutoSignal(!autoSignal)} />
      </div>

      {/* 2. AI Intelligence Config */}
      <div className="bg-white p-8 rounded-[24px] border border-gray-100 shadow-[0_4px_20px_rgba(0,0,0,0.02)]">
        <h3 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-6 flex items-center gap-2">
            <BrainCircuit size={16} className="text-gray-400" /> Intelligence Core
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* LLM Provider Selection */}
          <div>
            <label className="block text-xs font-bold text-gray-900 mb-3 uppercase tracking-wide">LLM Provider</label>
            <div className="flex bg-gray-50 p-1.5 rounded-xl border border-gray-100">
              {['openai', 'anthropic'].map((model) => (
                <button
                  key={model}
                  onClick={() => setProvider(model)}
                  className={`flex-1 py-2.5 text-xs font-black uppercase tracking-wider rounded-lg transition-all ${
                    provider === model 
                    ? 'bg-white text-[#824199] shadow-sm border border-gray-200' 
                    : 'text-gray-400 hover:text-gray-600'
                  }`}
                >
                  {model}
                </button>
              ))}
            </div>
          </div>

          {/* Timeframe Selection */}
          <div>
            <label className="block text-xs font-bold text-gray-900 mb-3 uppercase tracking-wide">Base Timeframe</label>
            <div className="flex bg-gray-50 p-1.5 rounded-xl border border-gray-100">
              {['1h', '4h', '1d'].map((tf) => (
                <button
                  key={tf}
                  onClick={() => setTimeframe(tf)}
                  className={`flex-1 py-2.5 text-xs font-black uppercase tracking-wider rounded-lg transition-all ${
                    timeframe === tf 
                    ? 'bg-white text-[#824199] shadow-sm border border-gray-200' 
                    : 'text-gray-400 hover:text-gray-600'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 3. Risk Management Config */}
      <div className="bg-white p-8 rounded-[24px] border border-gray-100 shadow-[0_4px_20px_rgba(0,0,0,0.02)]">
        <h3 className="text-[11px] font-black text-gray-400 uppercase tracking-[0.2em] mb-6 flex items-center gap-2">
            <Activity size={16} className="text-gray-400" /> Virtual Risk Parameters
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* Risk Appetite */}
          <div>
            <label className="block text-xs font-bold text-gray-900 mb-3 uppercase tracking-wide">Signal Risk Appetite</label>
            <div className="flex flex-col gap-2">
              {['Conservative', 'Moderate', 'Aggressive'].map((level) => (
                <button
                  key={level}
                  onClick={() => setRiskLevel(level)}
                  className={`flex items-center justify-between px-4 py-3 rounded-xl border transition-all ${
                    riskLevel === level 
                    ? 'border-[#824199] bg-purple-50/50' 
                    : 'border-gray-100 bg-white hover:border-gray-200'
                  }`}
                >
                  <span className={`text-sm font-bold ${riskLevel === level ? 'text-[#824199]' : 'text-gray-600'}`}>{level}</span>
                  <div className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${riskLevel === level ? 'border-[#824199]' : 'border-gray-300'}`}>
                      {riskLevel === level && <div className="w-2 h-2 bg-[#824199] rounded-full" />}
                  </div>
                </button>
              ))}
            </div>
            <p className="text-[10px] text-gray-400 mt-3 leading-relaxed">
              *ระดับความเสี่ยงจะถูกใช้คำนวณจุดแนะนำตัดขาดทุน (Suggested SL)
            </p>
          </div>

          <div className="flex flex-col gap-6">
              {/* Max Daily Loss (Virtual) */}
              <div>
                <label className="block text-xs font-bold text-gray-900 mb-3 uppercase tracking-wide">Pause Signal Drawdown</label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                    <TrendingDown size={16} className="text-gray-400" />
                  </div>
                  <input 
                    type="number" 
                    defaultValue={5000}
                    className="w-full pl-10 pr-12 py-3 bg-gray-50 border border-gray-100 rounded-xl text-sm font-black text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#824199]/20 focus:border-[#824199] transition-all"
                  />
                  <div className="absolute inset-y-0 right-0 pr-4 flex items-center pointer-events-none">
                    <span className="text-xs font-black text-gray-400">THB</span>
                  </div>
                </div>
                <p className="text-[10px] text-gray-400 mt-2">AI จะหยุดส่งสัญญาณใหม่ชั่วคราว หากพอร์ตจำลองขาดทุนถึงขีดจำกัดนี้</p>
              </div>

              {/* Dynamic Trailing Stop */}
              <div className="p-5 bg-purple-50/50 border border-purple-100 rounded-xl flex items-start justify-between gap-4">
                  <div>
                      <p className="text-xs font-black text-gray-900 flex items-center gap-1.5 mb-1"><Crosshair size={14} className="text-[#824199]"/> Dynamic Trailing Alerts</p>
                      <p className="text-[10px] text-gray-500 font-medium">แนะนำจุดเลื่อน Stop Loss เพื่อล็อกกำไรอัตโนมัติด้วย ATR</p>
                  </div>
                  <ToggleSwitch enabled={trailingStop} onChange={() => setTrailingStop(!trailingStop)} />
              </div>
          </div>
        </div>
      </div>

      {/* 4. Danger Zone (Halt System) */}
      <div className="bg-gradient-to-br from-rose-500 to-rose-700 p-8 rounded-[24px] shadow-lg shadow-rose-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-6 relative overflow-hidden">
        <div className="absolute -right-10 -top-10 opacity-10 pointer-events-none">
            <AlertOctagon size={150} />
        </div>
        <div className="relative z-10">
           <h3 className="text-lg font-black text-white flex items-center gap-2 mb-1.5">
            <AlertOctagon size={20} /> Halt AI Signals (Kill Switch)
          </h3>
          <p className="text-sm text-rose-100 font-medium max-w-md">
            ระงับการทำงานของ AI และหยุดการแจ้งเตือนสัญญาณทุกประเภททันที ในกรณีที่เกิดเหตุการณ์วิกฤต (Black Swan Event)
          </p>
        </div>
        <button className="relative z-10 px-8 py-3.5 bg-white text-rose-600 text-xs font-black rounded-xl shadow-lg hover:scale-105 hover:bg-rose-50 transition-all uppercase tracking-widest whitespace-nowrap">
          Halt System
        </button>
      </div>

      {/* Save Action */}
      <div className="flex justify-end mt-4">
        <button className="px-10 py-4 bg-[#1a0a24] text-white text-sm font-black uppercase tracking-widest rounded-2xl shadow-[0_10px_30px_rgba(26,10,36,0.15)] hover:shadow-[0_10px_40px_rgba(130,65,153,0.3)] hover:bg-[#2d1040] transition-all flex items-center gap-2">
          <Cpu size={18} /> Apply Configuration
        </button>
      </div>
    </div>
  );
};

const ToggleSwitch = ({ enabled, onChange }: any) => (
  <button 
    onClick={onChange}
    className={`relative inline-flex h-8 w-14 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-300 ease-in-out focus:outline-none ${enabled ? 'bg-[#824199]' : 'bg-gray-200'}`}
  >
    <span className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow-md ring-0 transition duration-300 ease-in-out ${enabled ? 'translate-x-6' : 'translate-x-0'}`} />
  </button>
);
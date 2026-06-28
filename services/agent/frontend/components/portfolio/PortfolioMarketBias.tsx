import React, { useState, useEffect } from 'react';
import { Brain, TrendingUp, TrendingDown, Minus } from 'lucide-react';

export const PortfolioMarketBias = () => {
  const [bias, setBias] = useState({ direction: 'Neutral', conviction: 0, reason: 'Loading analysis...' });

  useEffect(() => {
  const fetchBias = async () => {
    try {
      // ดึง URL มาจากตัวแปรกลางที่คุณตั้งค่าไว้ (เช่น BASE หรือ import.meta.env.VITE_API_URL)
      const response = await fetch(`${BASE}/api/market-bias`);
      const data = await response.json();
      setBias(data);
    } catch (e) { 
      console.error("Error fetching bias:", e); 
    }
  };

  fetchBias();
  const interval = setInterval(fetchBias, 15000); // อัปเดตทุก 15 วินาที
  
  return () => clearInterval(interval);
}, []);

  // ฟังก์ชันเลือก UI ตามทิศทางตลาด
  const getUIConfig = () => {
    switch (bias.direction) {
      case 'Bullish':
        return { color: 'text-emerald-600', bg: 'bg-emerald-400', icon: <TrendingUp size={32} />, border: 'border-emerald-100' };
      case 'Bearish':
        return { color: 'text-rose-600', bg: 'bg-rose-400', icon: <TrendingDown size={32} />, border: 'border-rose-100' };
      default:
        return { color: 'text-gray-400', bg: 'bg-gray-400', icon: <Minus size={32} />, border: 'border-gray-100' };
    }
  };

  const ui = getUIConfig();

  return (
    <div className="bg-gradient-to-br from-[#fcfcfd] to-purple-50/30 p-6 rounded-[24px] border border-[#824199]/10 shadow-sm flex flex-col h-full transition-all">
      <div className="flex items-center gap-2 mb-6">
         <Brain size={18} className="text-[#824199]" />
         <h3 className="text-sm font-bold text-gray-900">Agent Market Bias</h3>
      </div>

      <div className="flex-1 flex flex-col justify-center items-center text-center">
        <div className="relative mb-3">
          <div className={`absolute inset-0 ${ui.bg} blur-xl opacity-20 rounded-full animate-pulse`}></div>
          <div className={`w-16 h-16 bg-white rounded-full shadow-md border ${ui.border} flex items-center justify-center relative z-10 ${ui.color}`}>
             {ui.icon}
          </div>
        </div>
        
        <p className={`text-2xl font-black ${ui.color} tracking-tight uppercase`}>{bias.direction}</p>
        
        <div className="flex items-center gap-2 mt-2 bg-white px-3 py-1.5 rounded-full border border-gray-100 shadow-sm">
           <span className="text-[10px] font-bold text-gray-400 uppercase">Conviction Score</span>
           <span className="text-xs font-black text-[#824199]">{bias.conviction}%</span>
        </div>
      </div>

      <div className="mt-4 pt-4 border-t border-gray-100/50">
        <p className="text-[11px] text-gray-500 italic leading-relaxed text-center">"{bias.reason}"</p>
      </div>
    </div>
  );
};
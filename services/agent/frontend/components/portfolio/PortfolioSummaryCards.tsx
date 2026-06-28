import React, { useState, useEffect } from 'react';
import { Target, TrendingUp, TrendingDown } from 'lucide-react';

export const PortfolioSummaryCards = () => {
  const [portfolioData, setPortfolioData] = useState({
    allTimeReturn: 0,
    growthStatus: 'Loading'
  });

  useEffect(() => {
    const fetchSummary = async () => {
      try {
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/portfolio-summary`);
        if (response.ok) {
          const data = await response.json();
          setPortfolioData(data);
        }
      } catch (error) {
        console.error("Error fetching summary:", error);
      }
    };
    fetchSummary();
  }, []);
  
  return (
    <div className="grid grid-c
    ols-1 md:grid-cols-4 gap-6">
      
      {/* 🚀 NEW DESIGN: ALL-TIME RETURN (DARK GAUGE) 🚀 */}
      <div className="md:col-span-2 relative bg-gradient-to-br from-[#0f172a] via-[#1a0a24] to-[#0f172a] p-8 rounded-[32px] border border-white/5 shadow-2xl overflow-hidden flex flex-col items-center justify-center text-center">
        
        {/* Background Glow Effect ให้กล่องดูไม่แบน */}
        <div className="absolute inset-0 bg-gradient-to-t from-emerald-500/5 to-transparent blur-[80px] -translate-y-1/2" />
        <div className="absolute -bottom-10 -right-10 w-48 h-48 bg-[#824199]/10 rounded-full blur-[70px]" />

        {/* 1. Header (Centered) */}
        <div className="relative z-10 flex flex-col items-center mb-6">
          <div className="flex items-center gap-2 mb-2 px-3 py-1 bg-white/5 border border-white/10 rounded-full">
            <Target size={12} className="text-white/40" />
            <p className="text-[10px] font-bold text-white/50 uppercase tracking-[0.2em]">Overall Return</p>
          </div>
          <p className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-1.5">
             {portfolioData.growthStatus === 'Bullish' ? <TrendingUp size={14}/> : <TrendingDown size={14}/>}
             Long-Term Growth
          </p>
        </div>

        {/* 2. Main Number (Centered with Glow) */}
        <div className="relative z-10 flex items-baseline gap-1.5">
           <p className="text-6xl font-black text-white tracking-tighter shadow-xl">
              +{portfolioData.allTimeReturn.toFixed(1)}
           </p>
           <span className="text-4xl font-bold text-emerald-400">%</span>
        </div>

        {/* 3. Segmented Gauge Line (Full Width for Balance) */}
        <div className="relative z-10 mt-7 w-full flex gap-1 h-1.5 opacity-60">
          {[...Array(12)].map((_, i) => (
             <div key={i} className="flex-1 rounded-[1px] bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.3)]"></div>
          ))}
          {[...Array(3)].map((_, i) => (
             <div key={i} className="flex-1 rounded-[1px] bg-white/10"></div>
          ))}
        </div>
        <p className="relative z-10 mt-2 text-[10px] font-bold text-white/30 uppercase tracking-wider">Historical Performance</p>

      </div>

      {/* ... (กล่อง Available Cash และ Floating P&L เดิมของคุณ) ... */}

    </div>
  );
};
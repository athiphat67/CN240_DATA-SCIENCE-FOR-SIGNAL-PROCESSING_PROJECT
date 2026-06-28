import React, { useState, useEffect } from 'react';
import { ShieldCheck, Crosshair } from 'lucide-react';

export const PortfolioMargin = () => {
  const [marginData, setMarginData] = useState({
    used: 0,
    free: 0,
    level: 0,
    leverage: '1:100',
    status: 'Syncing...'
  });

  useEffect(() => {
    const fetchMargin = async () => {
      try {
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/portfolio-margin`);
        if (response.ok) {
          const data = await response.json();
          setMarginData(data);
        }
      } catch (error) {
        console.error("Error fetching margin data:", error);
      }
    };
    fetchMargin();
    const interval = setInterval(fetchMargin, 10000);
    return () => clearInterval(interval);
  }, []);

  const total = marginData.used + marginData.free;
  const usedPct = total > 0 ? (marginData.used / total) * 100 : 0;
  return (
    <div className="relative bg-gradient-to-br from-[#0f172a] to-[#1a0a24] p-6 rounded-[24px] border border-white/10 shadow-xl overflow-hidden flex flex-col h-full">

      {/* Background Glow Effect ให้ดูมีมิติ */}
      <div className="absolute -top-20 -right-20 w-48 h-48 bg-emerald-500/20 blur-[60px] rounded-full pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-full h-1/2 bg-gradient-to-t from-black/20 to-transparent pointer-events-none" />

      {/* Header */}
      <div className="flex items-center justify-between mb-6 relative z-10">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center backdrop-blur-sm">
            <ShieldCheck size={16} className="text-emerald-400" />
          </div>
          <h3 className="text-sm font-bold text-white/90 tracking-wide">Risk Center</h3>
        </div>
        <span className="flex items-center gap-1.5 px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 rounded-full text-[10px] font-bold text-emerald-400 uppercase tracking-widest backdrop-blur-md shadow-[0_0_15px_rgba(16,185,129,0.1)]">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          {marginData.status}
        </span>
      </div>

      {/* Main Metric (Margin Level) */}
      <div className="relative z-10 mb-6 flex-1 flex flex-col justify-center">
        <p className="text-[10px] font-bold text-white/40 uppercase tracking-widest mb-1 flex items-center gap-1.5">
          <Crosshair size={12} /> Margin Level
        </p>
        <div className="flex items-end gap-2">
          <p className="text-[40px] font-black text-white tracking-tight leading-none">{marginData.level}</p>
          <p className="text-lg font-bold text-emerald-400 mb-1">%</p>
        </div>

        {/* Segmented Risk Gauge (แถบความเสี่ยงแบบขีดๆ ดูไฮเทค) */}
        <div className="mt-5 flex gap-1 h-2 w-full">
          {[...Array(10)].map((_, i) => {
            // คำนวณสีของแต่ละขีด
            const threshold = i * 10;
            let color = "bg-white/10"; // สีเทาขุ่น (ขีดที่ยังไม่ถึง)

            if (usedPct > threshold || (i === 0 && usedPct > 0)) {
              // เปลี่ยนสีตามระดับความเสี่ยง (เขียว -> เหลือง -> แดง)
              color = i > 7 ? "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.5)]" :
                i > 5 ? "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.5)]" :
                  "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]";
            }

            return (
              <div
                key={i}
                className={`flex-1 rounded-[1px] ${color} transition-all duration-500`}
              />
            );
          })}
        </div>
        <div className="flex justify-between mt-2 text-[9px] font-bold text-white/30 uppercase tracking-wider">
          <span>0% (Idle)</span>
          <span>Danger (100%)</span>
        </div>
      </div>

      {/* Stats Grid (กล่องข้อมูลด้านล่าง) */}
      <div className="grid grid-cols-2 gap-3 relative z-10">
        <div className="bg-white/5 border border-white/5 p-3 rounded-[16px] backdrop-blur-md hover:bg-white/10 transition-colors">
          <p className="text-[9px] font-bold text-white/40 uppercase tracking-widest mb-1">Used Margin</p>
          <p className="text-[13px] font-black text-white font-mono">{marginData.used.toLocaleString()} <span className="text-[10px] text-white/50">฿</span></p>
        </div>
        <div className="bg-white/5 border border-white/5 p-3 rounded-[16px] backdrop-blur-md hover:bg-white/10 transition-colors">
          <p className="text-[9px] font-bold text-white/40 uppercase tracking-widest mb-1">Free Margin</p>
          <p className="text-[13px] font-black text-emerald-400 font-mono">{marginData.free.toLocaleString()} <span className="text-[10px] text-emerald-400/50">฿</span></p>
        </div>
        <div className="col-span-2 bg-white/5 border border-white/5 py-2.5 px-4 rounded-[16px] backdrop-blur-md flex justify-between items-center">
          <p className="text-[10px] font-bold text-white/50 uppercase tracking-widest">Account Leverage</p>
          <p className="text-xs font-black text-white tracking-widest">{marginData.leverage}</p>
        </div>
      </div>

    </div>
  );
};
import React, { useState, useEffect } from 'react';
import { ArrowUpRight } from 'lucide-react';

// 💡 สร้าง Interface สำหรับรับข้อมูลจาก API
interface BreakdownData {
  accuracy: number;        // เช่น 85.4
  trend: number;           // เช่น 3.2
  trend_direction: 'up' | 'down';
  chart_data: number[];    // Array ของแท่งกราฟ (0-100) เช่น [40, 55, 72, 50, ...]
  last_confidence?: number;
}

export const SignalBreakdown = () => {
  const [grossFilter, setGrossFilter] = useState<string>('All');
  const [data, setData] = useState<BreakdownData | null>(null);
  const [loading, setLoading] = useState(true);

  // 💡 Effect ดึงข้อมูลทุกครั้งที่เปลี่ยน Filter
  useEffect(() => {
    const fetchBreakdown = async () => {
      setLoading(true);
      try {
        // Backend ต้องทำ Endpoint นี้มารองรับรับ query string `?filter=All`
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/signal-breakdown?filter=${grossFilter}`);
        if (response.ok) {
          const result = await response.json();
          setData(result);
        }
      } catch (error) {
        console.error("Failed to fetch signal breakdown:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchBreakdown();
  }, [grossFilter]);

  // หากกำลังโหลด หรือไม่มีข้อมูล แสดง Skeleton Loading
  if (loading || !data) {
    return (
      <div className="bg-white rounded-[24px] p-6 shadow-[0_4px_20px_rgba(0,0,0,0.04)] h-full animate-pulse">
        <div className="h-6 w-32 bg-gray-200 rounded mb-2"></div>
        <div className="h-10 w-24 bg-gray-200 rounded mb-5"></div>
        <div className="h-[200px] bg-gray-100 rounded-xl mb-4"></div>
        <div className="h-8 w-full bg-gray-200 rounded"></div>
      </div>
    );
  }

  // ป้องกันกราฟแท่งว่างเปล่า
  const barHeights = data.chart_data && data.chart_data.length > 0 ? data.chart_data : [0];
  const lastConfidence = data.last_confidence || barHeights[barHeights.length - 1];

  return (
    <div className="bg-white rounded-[24px] p-6 shadow-[0_4px_20px_rgba(0,0,0,0.04)] h-full flex flex-col font-sans">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-bold text-gray-900 tracking-tight">Signal Breakdown</h2>
        <button className="w-7 h-7 rounded-full border border-gray-200 flex items-center justify-center text-gray-400 hover:text-[#824199] hover:border-[#824199] transition-all">
          <ArrowUpRight size={14} />
        </button>
      </div>
      <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">Accuracy this month</p>
      <p className="text-4xl font-black text-gray-900 mb-5 tracking-tight flex items-center gap-3">
        {data.accuracy.toFixed(1)}%
        <span className={`text-sm font-bold px-2 py-0.5 rounded-md ${data.trend_direction === 'up' ? 'text-emerald-600 bg-emerald-50' : 'text-rose-600 bg-rose-50'}`}>
          {data.trend_direction === 'up' ? '↑' : '↓'} {Math.abs(data.trend).toFixed(1)}%
        </span>
      </p>

      {/* 📊 Bar chart */}
      <div className="relative flex-grow min-h-[200px]" style={{ height: 200 }}>
        <div className="absolute left-0 top-0 h-full flex flex-col justify-between text-[10px] font-bold text-gray-300 pr-3" style={{ width: 32 }}>
          <span>100%</span><span>80%</span><span>60%</span><span>40%</span><span>20%</span><span></span>
        </div>
        
        <div className="absolute left-8 right-0 bottom-0 top-0 flex items-end gap-1.5 pb-0">
          {/* วาดแท่งกราฟทั้งหมด (ยกเว้น 2 แท่งสุดท้ายเพื่อโชว์ Highlight) */}
          {barHeights.slice(0, -2).map((h, i) => (
            <div
              key={i}
              className="flex-1 rounded-t-md transition-all duration-700 hover:opacity-100"
              style={{
                height: `${h}%`,
                background: 'linear-gradient(180deg, #824199 0%, #5c2d6b 100%)',
                opacity: 0.3,
              }}
            />
          ))}
          
          {/* Highlight 2 แท่งสุดท้าย (ถ้ามีข้อมูลพอ) */}
          {barHeights.length >= 2 && (
            <div className="relative flex gap-1.5 items-end h-full">
              {/* Tooltip ลอยเหนือแท่งล่าสุด */}
              <div
                className="absolute text-center whitespace-nowrap z-10 rounded-xl px-3 py-1.5 text-[11px] text-white font-bold shadow-lg border border-white/10"
                style={{ background: '#1a0a24', bottom: `${barHeights[barHeights.length - 1] + 5}%`, left: '50%', transform: 'translateX(-50%)' }}
              >
                {lastConfidence}% <span className="text-white/50 font-normal">conf</span> · <span className="text-[#f9d443]">ล่าสุด</span>
              </div>
              
              {/* แท่งรองสุดท้าย */}
              <div
                className="rounded-t-md"
                style={{ height: `${barHeights[barHeights.length - 2]}%`, width: 36, background: 'linear-gradient(180deg, #824199 0%, #5c2d6b 100%)', opacity: 0.8 }}
              />
              {/* แท่งสุดท้าย (เด่นสุด) */}
              <div
                className="rounded-t-md shadow-[0_0_15px_rgba(249,212,67,0.4)]"
                style={{ height: `${barHeights[barHeights.length - 1]}%`, width: 36, background: 'linear-gradient(180deg, #f9d443 0%, #d97706 100%)' }}
              />
            </div>
          )}
        </div>
      </div>

      {/* 🎛 Filter tabs */}
      <div className="flex items-center gap-2 mt-4 pt-4 border-t border-gray-100">
        {['All', 'BUY', 'SELL', 'HOLD'].map((f) => (
          <button
            key={f}
            onClick={() => setGrossFilter(f)}
            className={`text-[11px] px-4 py-1.5 rounded-full cursor-pointer transition-all font-bold tracking-wider ${
              grossFilter === f
                ? 'bg-gray-900 text-white shadow-md'
                : 'bg-gray-50 text-gray-400 hover:text-gray-700 hover:bg-gray-100 border border-gray-100'
            }`}
          >
            {f}
          </button>
        ))}
      </div>
    </div>
  );
};
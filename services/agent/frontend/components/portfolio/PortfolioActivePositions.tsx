import React, { useState, useEffect } from 'react';
import { Activity, XCircle } from 'lucide-react';

// 1. กำหนด Interface ให้ตรงกับข้อมูลที่ Backend จะส่งมา
interface Position {
  id: string | number;
  asset: string;
  type: 'BUY' | 'SELL';
  size: string; 
  entry: number;
  current: number;
  tp: number;
  sl: number;
  openTime: string;
  duration?: string;
  pnl: number;
  pnlPercent: number;
}

export const PortfolioActivePositions = () => {
  // 2. สร้าง State สำหรับเก็บ Positions
  const [positions, setPositions] = useState<Position[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // 3. Fetch ข้อมูลจาก Backend
  const fetchPositions = async () => {
    try {
      // 💡 ใช้ตัวแปร BASE เพื่อให้รองรับทั้ง Local และ Production
      const response = await fetch(`${BASE}/api/active-positions`);
      
      if (!response.ok) throw new Error('Failed to fetch positions');
      const data = await response.json();
      setPositions(data);
    } catch (error) {
      console.error('Error fetching active positions:', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPositions();
    const interval = setInterval(fetchPositions, 10000); // อัปเดตทุก 10 วินาที
    return () => clearInterval(interval);
  }, []);

  // 4. คำนวณ Total Unrealized P&L แบบไดนามิกจากรายการที่เปิดอยู่
  const totalUnrealized = positions.reduce((sum, pos) => sum + pos.pnl, 0);

  return (
    <div className="bg-white rounded-[24px] shadow-sm border border-gray-100 overflow-hidden font-sans flex flex-col h-[480px]">
      
      <div className="p-5 border-b border-gray-50 flex items-center justify-between shrink-0 bg-white">
         <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center text-emerald-500">
               <Activity size={20} />
            </div>
            <div>
               <h3 className="text-sm font-bold text-gray-900">Active Positions</h3>
               <p className="text-[11px] text-gray-400 font-medium tracking-tight">Current market exposure</p>
            </div>
         </div>
         <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-3 py-1.5 rounded-full uppercase tracking-wider border border-emerald-100">
            {isLoading ? "..." : positions.length} Running
         </span>
      </div>

      <div className="grid grid-cols-[1.2fr_0.5fr_1fr_1fr_1fr_0.5fr] bg-gray-50/50 text-[10px] font-bold text-gray-400 uppercase tracking-wider p-4 border-b border-gray-100 shrink-0">
        <span>Asset</span>
        <span className="text-center">Side</span>
        <span className="text-right">Size/Entry</span>
        <span className="text-right">Target</span>
        <span className="text-right">P&L</span>
        <span className="text-right pr-2"></span>
      </div>

      <div className="divide-y divide-gray-50 overflow-y-auto flex-1 relative">
        {isLoading ? (
          // Loading State
          <div className="absolute inset-0 flex flex-col items-center justify-center opacity-50 bg-white/50 backdrop-blur-sm z-10">
             <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mb-2" />
             <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Loading...</p>
          </div>
        ) : null}

        {positions.length > 0 ? (
          positions.map((pos) => (
            <div key={pos.id} className="grid grid-cols-[1.2fr_0.5fr_1fr_1fr_1fr_0.5fr] items-center p-4 hover:bg-gray-50/50 transition-all">
               <div className="flex items-center gap-2">
                  <div className={`w-1 h-6 rounded-full ${pos.pnl >= 0 ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                  <div>
                     <p className="text-xs font-black text-gray-900">{pos.asset}</p>
                     <p className="text-[9px] text-gray-400 font-medium">{pos.openTime}</p>
                  </div>
               </div>
               <div className="flex justify-center">
                  <span className={`text-[9px] font-black px-2 py-0.5 rounded-md border ${pos.type === 'BUY' ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-rose-50 text-rose-600 border-rose-100'}`}>
                     {pos.type}
                  </span>
               </div>
               <div className="text-right">
                  <p className="text-[11px] font-bold text-gray-900">{pos.size}</p>
                  <p className="text-[9px] text-gray-500 font-medium">@{pos.entry.toLocaleString()}</p>
               </div>
               <div className="text-right">
                  <p className="text-[9px] font-bold text-emerald-600">TP: {pos.tp ? pos.tp.toLocaleString() : '-'}</p>
                  <p className="text-[9px] font-bold text-rose-400 mt-0.5">SL: {pos.sl ? pos.sl.toLocaleString() : '-'}</p>
               </div>
               <div className="text-right">
                  <div className={`flex items-center justify-end gap-1 text-[13px] font-black ${pos.pnl >= 0 ? 'text-emerald-600' : 'text-rose-500'}`}>
                     {pos.pnl > 0 ? '+' : ''}{pos.pnl.toLocaleString()}
                  </div>
                  <p className={`text-[9px] font-bold ${pos.pnl >= 0 ? 'text-emerald-500/70' : 'text-rose-400/70'}`}>
                     {pos.pnl > 0 ? '+' : ''}{pos.pnlPercent}%
                  </p>
               </div>
               <div className="text-right pr-2">
                  <button className="text-gray-300 hover:text-rose-500 transition-colors" title="Close Position">
                     <XCircle size={16} />
                  </button>
               </div>
            </div>
          ))
        ) : (
          !isLoading && (
            <div className="h-full flex flex-col items-center justify-center py-20 opacity-40">
               <Activity size={40} className="text-gray-300 mb-2" />
               <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest text-center">No Active Positions<br/><span className="lowercase font-medium">Monitoring market...</span></p>
            </div>
          )
        )}
      </div>

      <div className="px-6 py-3 bg-gray-50/80 border-t border-gray-100 flex justify-between items-center shrink-0">
         <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Total Unrealized</p>
         <p className={`text-sm font-black ${totalUnrealized >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
            {totalUnrealized > 0 ? '+' : ''}{totalUnrealized.toLocaleString()} ฿
         </p>
      </div>
    </div>
  );
};
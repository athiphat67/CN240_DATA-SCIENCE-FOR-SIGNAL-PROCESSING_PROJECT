import React, { useState, useEffect } from 'react';
import { TrendingUp, Zap, MinusCircle, AlertTriangle, Clock, ChevronDown, Activity } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Dot } from 'recharts';

export const SignalPerformanceChart = () => {
  const [data, setData] = useState([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchChartData = async () => {
      try {
        // 1. กำหนด API_URL โดยดึงจาก env (ถ้าไม่มีให้กลับไปใช้ localhost)
        const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

        // 2. เสียบตัวแปรเข้าไปใน fetch ด้วยเครื่องหมาย ` (Backtick)
        const response = await fetch(`${API_URL}/api/performance-chart?limit=50`);
        const result = await response.json();
        setData(result);
      } catch (error) {
        console.error("Error fetching chart data:", error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchChartData();
  }, []);

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const info = payload[0].payload;
      const hasSignal = !!info.action;

      return (
        <div className="bg-[#1a0a24]/95 backdrop-blur-xl p-5 rounded-[24px] border border-white/10 shadow-2xl transition-all min-w-[200px]">
          <div className="flex items-center justify-between gap-6 mb-3">
            <div className="flex items-center gap-2 text-gray-400">
               <Clock size={12} />
               <p className="text-[10px] font-bold uppercase tracking-widest">{info.time}</p>
            </div>
            {hasSignal && (
              <span className="text-[10px] font-mono text-blue-300 bg-white/5 px-2 py-0.5 rounded-md border border-white/5">
                  ID: #{info.signalId}
              </span>
            )}
          </div>
          
          <p className="text-2xl font-black text-white mb-2 leading-none">
             {payload[0].value.toLocaleString()} <span className="text-sm font-normal text-white/40">฿/g</span>
          </p>

          {hasSignal ? (
            <div className={`mt-2 inline-flex items-center gap-2 px-3 py-1.5 rounded-xl text-[10px] font-black uppercase border shadow-lg ${
              info.action === 'BUY' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
              info.action === 'SELL' ? 'bg-rose-500/20 text-rose-400 border-rose-500/30' :
              'bg-amber-500/20 text-amber-400 border-amber-500/30'
            }`}>
              {info.action === 'BUY' && <Zap size={12} fill="currentColor" />}
              {info.action === 'SELL' && <AlertTriangle size={12} fill="currentColor" />}
              {info.action === 'HOLD' && <MinusCircle size={12} fill="currentColor" />}
              {info.action} SIGNAL
            </div>
          ) : (
             <div className="mt-2 text-[10px] font-medium text-gray-500 uppercase tracking-wider">
               Price Update
             </div>
          )}
        </div>
      );
    }
    return null;
  };

  const renderCustomDot = (props: any) => {
    const { cx, cy, payload } = props;
    if (!payload.action || payload.action === 'HOLD') return null; 
    let dotFill = payload.action === 'BUY' ? '#10b981' : payload.action === 'SELL' ? '#f43f5e' : '#f59e0b';
    return (
      <Dot cx={cx} cy={cy} r={5} fill={dotFill} stroke="#fff" strokeWidth={2.5} className="drop-shadow-[0_0_6px_rgba(0,0,0,0.3)] hover:r-7 transition-all duration-300" />
    );
  };

  if (isLoading) {
    return (
      <div className="h-[500px] w-full bg-white rounded-[48px] border-2 border-gray-100 shadow-sm flex flex-col items-center justify-center animate-pulse">
        <Activity className="text-blue-200 mb-4 animate-bounce" size={48} />
        <p className="text-gray-400 font-black tracking-widest text-sm">SYNCING MARKET DATA...</p>
      </div>
    );
  }

  return (
    <div className="relative font-sans group">
      
      {/* Visual Connector (Optional) */}
      <div className="absolute -top-10 left-1/2 -translate-x-1/2 w-[90%] h-10 border-x-2 border-t-2 border-dashed border-gray-200 rounded-t-[40px] opacity-40 pointer-events-none" />
      <div className="absolute -top-4 left-1/2 -translate-x-1/2 text-gray-300 pointer-events-none">
        <ChevronDown size={20} className="animate-bounce" />
      </div>

      <div className="bg-white p-8 md:p-10 rounded-[48px] border-2 border-gray-100 shadow-[0_30px_70px_-20px_rgba(0,0,0,0.05)] relative z-10 transition-all">
        
        {/* ✨ Header & Legend Box */}
        <div className="flex flex-col xl:flex-row xl:items-end justify-between mb-10 gap-6">
          <div>
            <div className="flex items-center gap-3 mb-2">
               <div className="w-1.5 h-6 bg-gradient-to-b from-blue-400 to-indigo-500 rounded-full" />
               <h3 className="text-[13px] font-black text-gray-400 uppercase tracking-[0.2em]">Market Action Trace</h3>
            </div>
            <h2 className="text-3xl font-black text-gray-900 tracking-tight pl-4.5 mb-1">
              Gold Price <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-500 italic">&</span> AI Signals
            </h2>
            <p className="text-[13px] font-medium text-gray-500 pl-4.5 max-w-lg">
              ติดตามการเคลื่อนไหวของราคาทองคำ พร้อมจุดแสดงสัญญาณ <strong className="text-emerald-500">ซื้อ (BUY)</strong> และ <strong className="text-rose-500">ขาย (SELL)</strong> จาก AI Agent แบบเรียลไทม์
            </p>
          </div>

          {/* ✨ Legend Badges */}
          <div className="flex flex-wrap items-center bg-gray-50/80 backdrop-blur-sm p-1.5 rounded-2xl border border-gray-100 shadow-inner gap-1">
              <LegendItem color="bg-blue-500" label="PRICE LINE" icon={<Activity size={10} className="text-white" />} />
              <div className="w-px h-4 bg-gray-200 mx-1"></div>
              <LegendItem color="bg-emerald-500" label="BUY SIGNAL" />
              <LegendItem color="bg-rose-500" label="SELL SIGNAL" />
              {/* ถ้าอยากโชว์อธิบาย HOLD ด้วยให้เปิดคอมเมนต์บรรทัดล่างครับ */}
              {/* <LegendItem color="bg-amber-500" label="HOLD" /> */}
          </div>
        </div>

        {/* Chart Area */}
        <div className="h-[380px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.2}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" opacity={0.8}/>
              <XAxis 
                dataKey="time" 
                axisLine={false} 
                tickLine={false} 
                tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 700 }} 
                dy={15} 
                interval="preserveStartEnd" 
                minTickGap={50} 
              />
              <YAxis 
                domain={['dataMin - 500', 'dataMax + 500']} 
                axisLine={false} 
                tickLine={false} 
                tick={{ fontSize: 11, fill: '#94a3b8', fontWeight: 600 }} 
                tickFormatter={(value) => `${(value / 1000).toFixed(1)}k`} 
                dx={-15} 
              />
              <Tooltip 
                content={<CustomTooltip />} 
                cursor={{ stroke: '#3b82f6', strokeWidth: 1.5, strokeDasharray: '4 4', opacity: 0.6 }} 
              />
              <Area 
                type="linear" 
                dataKey="price" 
                stroke="#3b82f6" 
                strokeWidth={3} 
                fillOpacity={1} 
                fill="url(#colorPrice)" 
                dot={renderCustomDot} 
                activeDot={{ r: 7, strokeWidth: 0, fill: '#3b82f6', className: "drop-shadow-md" }} 
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

      </div>
    </div>
  );
};

// Component ย่อยสำหรับทำ Legend อธิบายสี
const LegendItem = ({ color, label, icon }: any) => (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl hover:bg-white transition-colors cursor-default">
        <div className={`w-3.5 h-3.5 rounded-full ${color} shadow-[0_0_8px_rgba(0,0,0,0.15)] flex items-center justify-center`}>
            {icon}
        </div>
        <span className="text-[10px] font-black text-gray-600 tracking-widest uppercase">{label}</span>
    </div>
);
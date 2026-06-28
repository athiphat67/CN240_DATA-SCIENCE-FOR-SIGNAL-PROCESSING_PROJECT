import React, { useState, useEffect } from 'react';
import { Activity, Brain, Wifi, Clock, Zap, Target } from 'lucide-react';

// 1. กำหนด Interface สำหรับข้อมูล Health Status
interface SystemHealth {
  latency: number;
  iterations: number;
  api_status: 'Stable' | 'Warning' | 'Offline';
  accuracy: number;
  last_update: string;
  quality_score: number;
}

export const AgentHealthMonitor = () => {
  const [healthData, setHealthData] = useState<SystemHealth | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchHealth = async () => {
    try {
      // 💡 ใช้ตัวแปร BASE เพื่อให้รองรับทั้ง Local และ Production
      const response = await fetch(`${BASE}/api/agent-health`);
      
      if (!response.ok) throw new Error('Network error');
      const data = await response.json();
      setHealthData(data);
    } catch (error) {
      console.error('Error fetching health:', error);
      // กรณีดึงข้อมูลไม่ได้ ให้แสดงสถานะ Offline
      setHealthData(prev => ({
        ...prev,
        latency: 0,
        iterations: 0,
        api_status: 'Offline',
        accuracy: 0,
        last_update: 'Unknown',
        quality_score: 0
      } as SystemHealth));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 5000); // อัปเดตทุก 5 วินาทีเพราะเป็น Health Check
    return () => clearInterval(interval);
  }, []);

  // ฟังก์ชันคำนวณสีของสถานะตามเงื่อนไข
  const getStatusColor = (status: string) => {
    if (status === 'Stable') return 'bg-emerald-500';
    if (status === 'Warning') return 'bg-amber-500';
    return 'bg-rose-500';
  };

  const getStatusBg = (status: string) => {
    if (status === 'Stable') return 'bg-emerald-50 border-emerald-100/60 text-emerald-600';
    if (status === 'Warning') return 'bg-amber-50 border-amber-100/60 text-amber-600';
    return 'bg-rose-50 border-rose-100/60 text-rose-600';
  };

  // ใช้ Mock Data ป้องกัน UI พังระหว่างโหลด
  const data = healthData || {
    latency: 0, iterations: 0, api_status: 'Connecting...', accuracy: 0, last_update: '-', quality_score: 0
  };

  const isHealthy = data.api_status === 'Stable';

  return (
    <div className="relative bg-white rounded-[32px] border border-gray-100 shadow-[0_15px_35px_rgba(0,0,0,0.025)] p-6 overflow-hidden group hover:border-purple-200 transition-all duration-500 hover:shadow-[0_20px_50px_rgba(130,65,153,0.05)]">
      
      <div className="absolute top-0 right-0 w-48 h-48 bg-[#824199]/5 blur-[90px] rounded-full pointer-events-none" />

      <div className="flex flex-col gap-6 relative z-10">
        {/* Header Layout */}
        <div className="flex items-start justify-between">
          <div>
            {/* Dynamic Status Badge */}
            <div className={`flex items-center gap-2 px-3 py-1 border rounded-full w-fit mb-2 ${getStatusBg(data.api_status)}`}>
              <span className="relative flex h-2 w-2">
                <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${getStatusColor(data.api_status)}`}></span>
                <span className={`relative inline-flex rounded-full h-2 w-2 ${getStatusColor(data.api_status)}`}></span>
              </span>
              <p className="text-[10px] font-black uppercase tracking-widest">
                {isLoading ? 'Connecting...' : (isHealthy ? 'Active & Optimized' : data.api_status)}
              </p>
            </div>
            <h3 className="text-sm font-black text-gray-900 tracking-tight">Neural Engine</h3>
            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
              Version 3.2.0 <span className="text-gray-200">|</span> {data.last_update}
            </p>
          </div>
          
          <div className="relative group/icon">
            <div className={`absolute inset-0 blur-xl rounded-full opacity-50 group-hover/icon:opacity-100 animate-pulse ${isHealthy ? 'bg-purple-500/10' : 'bg-rose-500/20'}`} />
            <div className="w-14 h-14 rounded-3xl bg-gray-50 flex items-center justify-center border border-gray-100 group-hover:border-[#824199]/10 group-hover:bg-white transition-all duration-300 relative shadow-inner">
              <Brain size={28} className={`${isHealthy ? 'text-gray-300 group-hover:text-[#824199]' : 'text-rose-400'} transition-colors`} />
            </div>
            <div className="absolute -bottom-2 -left-2 w-6 h-6 bg-white rounded-full flex items-center justify-center border border-gray-100 shadow-sm">
                <Zap size={12} className={`${isHealthy ? 'text-amber-400 fill-amber-400' : 'text-gray-300'}`} />
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="space-y-3">
          {[
            { icon: <Clock size={14} />, label: 'Latency (Avg)', value: isLoading ? '-' : `${(data.latency / 1000).toFixed(2)}s`, color: 'text-purple-400' },
            { icon: <Wifi size={14} />, label: 'Market API Stream', value: data.api_status, color: isHealthy ? 'text-emerald-400' : 'text-rose-400' },
            { icon: <Activity size={14} />, label: 'ReAct Layers', value: isLoading ? '-' : `${data.iterations} Layers`, color: 'text-blue-400' },
            { icon: <Target size={14} />, label: 'System Confidence', value: isLoading ? '-' : `${data.accuracy}%`, color: 'text-rose-400' }
          ].map((item, i) => (
            <div key={i} className="flex items-center justify-between p-4 bg-gray-50/50 rounded-2xl hover:bg-gray-100 transition-colors border border-gray-100/50">
              <div className="flex items-center gap-3.5">
                <div className={`${item.color} w-8 h-8 rounded-xl bg-white flex items-center justify-center shadow-inner border border-gray-100`}>
                    {item.icon}
                </div>
                <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">{item.label}</p>
              </div>
              <p className="text-xs font-black text-gray-900 pr-2">{item.value}</p>
            </div>
          ))}
        </div>

        {/* Data Quality Bar */}
        <div className="pt-3 border-t border-gray-100/50 mt-1">
          <div className="flex justify-between items-center text-[10px] font-bold uppercase tracking-widest mb-3">
            <span className="text-gray-400 flex items-center gap-1.5"><Activity size={12} className="text-gray-300"/> Data Quality Score</span>
            <span className="text-emerald-500 font-extrabold">{isLoading ? '-' : 'High'}</span>
          </div>
          <div className="h-1.5 w-full bg-gray-100 rounded-full overflow-hidden p-[2px]">
             <div 
               className={`h-full rounded-full shadow-[0_0_10px_rgba(16,185,129,0.3)] transition-all duration-1000 ${isHealthy ? 'bg-gradient-to-r from-emerald-400 to-emerald-500' : 'bg-rose-400'}`}
               style={{ width: `${data.quality_score}%` }}
             ></div>
          </div>
        </div>
      </div>
    </div>
  );
};
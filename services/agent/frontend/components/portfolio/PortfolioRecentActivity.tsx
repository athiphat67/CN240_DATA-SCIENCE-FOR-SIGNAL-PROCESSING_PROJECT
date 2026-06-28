import React, { useState, useEffect } from 'react';
import { History, ArrowDownRight, ArrowUpRight, PlusCircle, Activity, Clock } from 'lucide-react';

// 1. กำหนด Interface ให้ตรงกับโครงสร้างข้อมูลที่จะได้รับจาก API
interface ActivityLog {
  id: number;
  type: 'Open' | 'Close' | 'Deposit' | 'Withdraw';
  asset: string;
  detail: string;
  time: string; // เช่น "2h ago" หรือ ISO String
  amount: string;
  color: string; // Tailwind class สำหรับสีข้อความ เช่น "text-emerald-500"
  bg: string;    // Tailwind class สำหรับสีพื้นหลังไอคอน เช่น "bg-emerald-50"
}

export const PortfolioRecentActivity = () => {
  // 2. สร้าง State สำหรับเก็บข้อมูลและสถานะการโหลด
  const [activities, setActivities] = useState<ActivityLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // 3. ฟังก์ชันดึงข้อมูลจาก Backend
  const fetchActivities = async () => {
    try {
      const response = await fetch(`${import.meta.env.VITE_API_URL}/api/recent-activity`);
      if (response.ok) {
        const data = await response.json();
        setActivities(data);
      } else {
        throw new Error('Failed to fetch activity logs');
      }
    } catch (error) {
      console.error("Error fetching activities:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchActivities();
    // อัปเดตข้อมูลทุก 30 วินาทีเพื่อให้เห็นรายการใหม่ๆ
    const interval = setInterval(fetchActivities, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="bg-gray-50/50 backdrop-blur-sm rounded-[32px] p-6 border border-gray-100 h-full flex flex-col font-sans">
      {/* Header */}
      <div className="p-4 border-b border-gray-100/50 flex items-center justify-between shrink-0">
         <h3 className="text-sm font-black text-gray-900 flex items-center gap-2 uppercase tracking-tight">
            <History size={18} className="text-[#824199]" />
            Recent Activity
         </h3>
         <button className="text-[10px] font-black text-[#824199] hover:text-[#6c3680] transition-colors uppercase tracking-widest bg-white px-3 py-1.5 rounded-lg border border-gray-100 shadow-sm">
            View All
         </button>
      </div>

      <div className="flex-1 overflow-y-auto mt-4 pr-2 custom-scrollbar">
        {isLoading ? (
          /* Loading State */
          <div className="h-full flex flex-col items-center justify-center opacity-40">
             <Activity size={32} className="text-purple-300 animate-spin mb-2" />
             <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Syncing logs...</p>
          </div>
        ) : activities.length === 0 ? (
          /* Empty State */
          <div className="h-full flex flex-col items-center justify-center py-20 opacity-30">
             <Clock size={40} className="text-gray-300 mb-2" />
             <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">No recent records</p>
          </div>
        ) : (
          <div className="space-y-6 relative ml-2">
            {/* Vertical Timeline Line */}
            <div className="absolute left-[15px] top-2 bottom-2 w-px bg-gray-200/50 -z-10"></div>

            {activities.map((act) => (
              <div key={act.id} className="flex gap-4 relative z-10 group">
                {/* Icon Column */}
                <div className={`w-8 h-8 rounded-full ${act.bg} ${act.color} flex items-center justify-center shrink-0 border-4 border-white shadow-sm transition-transform group-hover:scale-110`}>
                  {act.type === 'Close' && <ArrowDownRight size={14} strokeWidth={3} />}
                  {(act.type === 'Open' || act.type === 'Withdraw') && <ArrowUpRight size={14} strokeWidth={3} />}
                  {act.type === 'Deposit' && <PlusCircle size={14} strokeWidth={3} />}
                </div>

                {/* Content Column */}
                <div className="flex-1 pb-1 bg-white p-3 rounded-2xl border border-transparent hover:border-purple-100 transition-all hover:shadow-sm">
                  <div className="flex justify-between items-start mb-0.5">
                    <p className="text-xs font-black text-gray-900 uppercase tracking-tight">
                      {act.type} <span className="text-gray-400 ml-1">{act.asset}</span>
                    </p>
                    <p className={`text-[13px] font-black ${act.color}`}>
                      {act.amount}
                    </p>
                  </div>
                  <div className="flex justify-between items-center">
                    <p className="text-[11px] text-gray-500 font-medium">{act.detail}</p>
                    <p className="text-[9px] text-gray-400 font-bold uppercase tracking-tighter">
                      {act.time}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
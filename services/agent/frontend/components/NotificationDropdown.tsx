import React, { useState, useRef, useEffect } from 'react';
import { Bell, Target, TrendingUp, AlertTriangle, CheckCircle2, Activity } from 'lucide-react';

interface NotificationData {
  id: string;
  title: string;
  desc: string;
  time: string;
  type: 'success' | 'info' | 'warning' | 'system';
  isRead?: boolean;
}

// ⏳ ฟังก์ชันแปลง ISO Time เป็น "2m ago", "1h ago"
const timeAgo = (dateString: string) => {
  const date = new Date(dateString.replace('Z', '+00:00')); // รองรับ Timezone
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};

// 🎨 ฟังก์ชันเลือก Icon ตาม Type
const getIcon = (type: string) => {
  switch (type) {
    case 'success': return <Target size={18} />;
    case 'info': return <TrendingUp size={18} />;
    case 'warning': return <AlertTriangle size={18} />;
    default: return <CheckCircle2 size={18} />;
  }
};

export const NotificationDropdown = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationData[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // 💾 ดึง ID ของการแจ้งเตือนที่อ่านแล้วจาก LocalStorage (เพื่อไม่ให้มันกลับมาเด้งเหลืองอีกตอน Refresh)
  const [readIds, setReadIds] = useState<string[]>(() => {
    const saved = localStorage.getItem('readNotifications');
    return saved ? JSON.parse(saved) : [];
  });

  // 📡 ฟังก์ชันดึงข้อมูลจาก API
  const fetchNotifications = async () => {
    try {
      const response = await fetch(`${import.meta.env.VITE_API_URL}/api/notifications`);
      if (response.ok) {
        const data: NotificationData[] = await response.json();
        // เอามาเช็คกับ readIds ในเครื่องเรา
        const formattedData = data.map(notif => ({
          ...notif,
          isRead: readIds.includes(notif.id)
        }));
        setNotifications(formattedData);
      }
    } catch (error) {
      console.error("Failed to fetch notifications:", error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchNotifications();
    // Auto Refresh ทุกๆ 30 วินาที
    const interval = setInterval(fetchNotifications, 30000);
    return () => clearInterval(interval);
  }, [readIds]); // ใส่ readIds เป็น dependency เพื่อให้อัปเดตสถานะการอ่านได้ถูกต้อง

  // 🖱️ Click Outside Logic
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // ✔️ ฟังก์ชัน Mark All Read
  const handleMarkAllRead = () => {
    const allIds = notifications.map(n => n.id);
    setReadIds(allIds);
    localStorage.setItem('readNotifications', JSON.stringify(allIds));
    setNotifications(prev => prev.map(n => ({ ...n, isRead: true })));
  };

  const unreadCount = notifications.filter(n => !n.isRead).length;

  return (
    <div className="relative" ref={dropdownRef}>
      
      {/* --- ปุ่มกระดิ่งแจ้งเตือน --- */}
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2.5 rounded-2xl bg-white/5 border border-white/10 text-gray-400 hover:text-white hover:bg-white/10 transition-all focus:outline-none focus:ring-2 focus:ring-[#824199]/50"
      >
        <Bell size={20} strokeWidth={2} className={unreadCount > 0 ? "animate-[wiggle_1s_ease-in-out_infinite]" : ""} />
        {unreadCount > 0 && (
          <span className="absolute top-2.5 right-2.5 w-2.5 h-2.5 bg-[#FFD700] rounded-full border-2 border-[#1a0a24] shadow-[0_0_10px_rgba(255,215,0,0.6)]" />
        )}
      </button>

      {/* --- กล่อง Pop-up Dropdown --- */}
      {isOpen && (
        <div className="absolute right-0 mt-4 w-80 sm:w-[380px] bg-[#1a0a24]/95 backdrop-blur-2xl rounded-[24px] border border-white/10 shadow-[0_20px_60px_rgba(0,0,0,0.6)] overflow-hidden z-[100] animate-in fade-in slide-in-from-top-4 duration-200 origin-top-right">
          
          {/* Header */}
          <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between bg-gradient-to-r from-white/5 to-transparent">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              Notifications
              {unreadCount > 0 && (
                <span className="bg-[#824199] text-white text-[10px] px-2 py-0.5 rounded-full shadow-sm">
                  {unreadCount} New
                </span>
              )}
            </h3>
            {unreadCount > 0 && (
              <button 
                onClick={handleMarkAllRead}
                className="text-[10px] font-bold text-gray-400 hover:text-white uppercase tracking-widest transition-colors"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* รายการแจ้งเตือน */}
          <div className="max-h-[360px] overflow-y-auto custom-scrollbar">
            {isLoading ? (
               <div className="p-8 text-center flex flex-col items-center justify-center opacity-50">
                  <Activity className="animate-spin text-[#824199] mb-2" size={24} />
                  <p className="text-xs text-gray-400 uppercase tracking-widest">Syncing logs...</p>
               </div>
            ) : notifications.length > 0 ? (
              notifications.map((notif) => (
                <div 
                  key={notif.id} 
                  className={`p-4 border-b border-white/5 flex gap-4 hover:bg-white/5 transition-colors cursor-pointer ${notif.isRead ? 'opacity-60' : 'bg-white/[0.03]'}`}
                >
                  <div className={`w-10 h-10 rounded-2xl flex items-center justify-center shrink-0 border ${
                    notif.type === 'success' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' :
                    notif.type === 'warning' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' :
                    notif.type === 'info' ? 'bg-[#824199]/20 text-[#c084fc] border-[#824199]/30' :
                    'bg-gray-500/10 text-gray-400 border-gray-500/20'
                  }`}>
                    {getIcon(notif.type)}
                  </div>
                  <div className="flex-1">
                    <div className="flex justify-between items-start mb-1">
                      <p className={`text-sm font-bold leading-tight ${notif.isRead ? 'text-gray-300' : 'text-white'}`}>{notif.title}</p>
                      {!notif.isRead && <span className="w-2 h-2 bg-[#FFD700] rounded-full mt-1.5 shrink-0 shadow-[0_0_8px_rgba(255,215,0,0.5)]" />}
                    </div>
                    <p className="text-[11px] text-gray-400 leading-relaxed mt-1">{notif.desc}</p>
                    <p className="text-[9px] text-gray-500 font-bold mt-2 tracking-[0.1em] uppercase">{timeAgo(notif.time)}</p>
                  </div>
                </div>
              ))
            ) : (
              <div className="p-8 text-center text-gray-500">
                <Bell size={24} className="mx-auto mb-2 opacity-50" />
                <p className="text-sm">No new notifications</p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="p-3 border-t border-white/5 bg-black/20 text-center hover:bg-black/30 transition-colors cursor-pointer">
            <button className="text-[10px] font-bold text-[#c084fc] hover:text-white transition-colors uppercase tracking-[0.2em] w-full py-1">
              View Signal History
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
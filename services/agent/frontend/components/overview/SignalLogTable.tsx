import React, { useState, useEffect } from 'react';
import { Crosshair, ShieldX, Clock } from 'lucide-react';
import { Link } from 'react-router-dom';

type SignalType = 'BUY' | 'HOLD' | 'SELL';

// 1. กำหนด Interface ให้ตรงกับที่ API ส่งมา
interface SignalLog {
  id: number;
  logged_at: string;
  interval_tf: string;
  entry_price: number | null;
  take_profit: number | null;
  stop_loss: number | null;
  signal: SignalType | null;
  confidence: number;
}

const SignalPill = ({ signal }: { signal: SignalType }) => {
  const styles: Record<SignalType, string> = {
    BUY: 'bg-emerald-100/80 text-emerald-700 border-emerald-200',
    HOLD: 'bg-amber-100/80 text-amber-700 border-amber-200',
    SELL: 'bg-rose-100/80 text-rose-700 border-rose-200',
  };
  
  return (
    <span className={`text-[11px] font-black px-3 py-1 rounded-full border tracking-wider ${styles[signal]}`}>
      {signal}
    </span>
  );
};

export const SignalLogTable = () => {
  const [logFilter, setLogFilter] = useState<'Recent' | 'All'>('Recent');
  const [signalLogs, setSignalLogs] = useState<SignalLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // 2. ดึงข้อมูลจาก Backend
  useEffect(() => {
    const fetchLogs = async () => {
      setIsLoading(true);
      try {
        const limit = logFilter === 'Recent' ? 10 : 50;
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/recent-signals?limit=${limit}`);
        
        if (response.ok) {
          const data = await response.json();
          setSignalLogs(data);
        } else {
          console.error(`Error: Received status ${response.status} from API`);
        }
      } catch (error) {
        console.error("Failed to fetch signal logs:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchLogs();
  }, [logFilter]);

  // ฟังก์ชันแปลงวันที่ (เช่น "2026-04-15T14:00:00Z" -> "15 Apr 14:00")
  const formatDate = (isoString: string) => {
    if (!isoString) return 'Unknown';
    const date = new Date(isoString);
    return date.toLocaleString('en-GB', { 
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' 
    }).replace(',', '');
  };

  return (
    <div className="bg-white rounded-[24px] p-6 shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-gray-50 mt-4 font-sans">
      <div className="flex items-center justify-between mb-6">
        <div>
           <h2 className="text-lg font-bold text-gray-900 tracking-tight">Intelligence History</h2>
           <p className="text-xs text-gray-400 mt-0.5">Track record of recent agent decisions</p>
        </div>
        
        <div className="bg-gray-50 p-1 rounded-xl border border-gray-100 flex items-center">
          {(['Recent', 'All'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setLogFilter(f)}
              className={`px-4 py-1.5 text-xs rounded-lg transition-all font-bold ${
                logFilter === f ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-400 hover:text-gray-600'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Table Header */}
      <div className="grid grid-cols-7 text-[11px] text-gray-400 font-bold uppercase tracking-wider pb-3 border-b border-gray-100 mb-3">
        <span className="col-span-1">Date & Time</span>
        <span className="col-span-1 text-center">TF</span>
        <span className="col-span-1 text-center">Action</span>
        <span className="col-span-2 text-center">Price Targets (THB/g)</span>
        <span className="col-span-1 text-center">Confidence</span>
        <span className="col-span-1 text-right pr-4">Est. P&L</span>
      </div>

      {/* Table Body */}
      {isLoading ? (
        <div className="py-10 flex justify-center items-center">
            <span className="text-sm font-medium text-gray-400 animate-pulse">Loading intelligence logs...</span>
        </div>
      ) : signalLogs.length === 0 ? (
        <div className="py-10 flex justify-center items-center">
            <span className="text-sm font-medium text-gray-400">No intelligence history found.</span>
        </div>
      ) : (
        <div className="divide-y divide-gray-50/50">
          {signalLogs.map((row) => {
  const safeSignal = row.signal || 'HOLD';
  const confPercent = row.confidence <= 1 ? Math.round(row.confidence * 100) : row.confidence;
  
  return (
    // เปลี่ยนจาก div มาเป็น Link โดยใส่ className grid เข้าไปที่นี่เลย
    <Link 
      key={row.id} 
      to={`/signals/${row.id}`} 
      className="grid grid-cols-7 text-sm py-4 items-center hover:bg-gray-50/80 transition-all duration-200 rounded-xl px-2 -mx-2 cursor-pointer border border-transparent hover:border-gray-100"
    >
      {/* Date */}
      <span className="col-span-1 text-gray-500 font-medium text-xs flex items-center gap-2">
        <Clock size={12} className="text-gray-300" />
        {formatDate(row.logged_at)}
      </span>
      
      {/* Timeframe */}
      <div className="col-span-1 flex justify-center">
        <span className="font-mono text-gray-500 text-xs bg-gray-100 px-2 py-0.5 rounded-md">
          {row.interval_tf || '-'}
        </span>
      </div>
      
      {/* Signal */}
      <div className="col-span-1 flex justify-center">
        <SignalPill signal={safeSignal} />
      </div>
      
      {/* Price Targets */}
      <div className="col-span-2 flex flex-col items-center gap-1">
        <div className="flex items-center gap-2 text-sm font-black text-gray-900">
          {row.entry_price ? row.entry_price.toLocaleString('en-US', { minimumFractionDigits: 2 }) : '—'} 
          {row.entry_price && <span className="text-[10px] text-gray-400 font-bold">ENTRY</span>}
        </div>
        {safeSignal !== 'HOLD' && (row.take_profit || row.stop_loss) && (
          <div className="flex items-center justify-center gap-3 text-[10px] font-bold">
            <span className="flex items-center gap-1 text-emerald-600">
              <Crosshair size={10}/> 
              {row.take_profit ? row.take_profit.toLocaleString('en-US', { minimumFractionDigits: 2 }) : '—'}
            </span>
            <span className="flex items-center gap-1 text-rose-500">
              <ShieldX size={10}/> 
              {row.stop_loss ? row.stop_loss.toLocaleString('en-US', { minimumFractionDigits: 2 }) : '—'}
            </span>
          </div>
        )}
      </div>
      
      {/* Confidence Bar */}
      <div className="col-span-1 flex justify-center items-center gap-3">
        <div className="w-16 xl:w-20 h-2 bg-gray-100 rounded-full overflow-hidden shadow-inner flex-shrink-0">
          <div
            className="h-full rounded-full bg-gradient-to-r from-[#824199] to-[#c084fc]"
            style={{ width: `${confPercent}%` }}
          />
        </div>
        <span className="text-[11px] font-black text-gray-700 w-8">{confPercent}%</span>
      </div>
      
      {/* P&L */}
      <span className="col-span-1 text-right pr-2 font-black text-sm text-gray-300">
        —
      </span>
    </Link>
  );
})}
        </div>
      )}
    </div>
  );
};
import React, { useState, useEffect } from "react";
import {
  Target,
  TrendingUp,
  Activity,
  BarChart2,
  AlertCircle,
} from "lucide-react";

export const SignalStatsCards = () => {
  const [stats, setStats] = useState({
    net_pnl: 0,
    win_rate: 0,
    total_signals: 0,
    active_signals: 0,
    weekly_growth: 0,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const response = await fetch(
          `${import.meta.env.VITE_API_URL}/api/signal-stats`,
        );
        if (response.ok) {
          const data = await response.json();
          setStats(data);
        }
      } catch (error) {
        console.error("Error fetching stats:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  if (loading)
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8 h-32 animate-pulse bg-gray-100 rounded-3xl" />
    );

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8 font-sans">
      {/* 🟣 Card 1: Net P&L */}
      <div className="group bg-gradient-to-br from-[#fdfaff] via-[#f5eefc] to-[#ede4f5] p-6 rounded-[24px] border-2 border-purple-200 hover:border-purple-400 shadow-lg transition-all duration-500 hover:-translate-y-1.5">
        <div className="flex items-center gap-2 mb-4 relative z-10">
          <div className="w-8 h-8 rounded-xl bg-white flex items-center justify-center text-[#824199] border-2 border-purple-100 shadow-sm">
            <BarChart2 size={16} strokeWidth={2.5} />
          </div>
          <h3 className="text-xs font-black text-purple-900/60 uppercase tracking-widest">Net P&L</h3>
        </div>
        <div className="relative z-10">
          <div className="flex items-baseline gap-2">
            <p className="text-4xl font-black text-transparent bg-clip-text bg-gradient-to-r from-purple-900 to-purple-500 tracking-tight">
              {(stats.net_pnl || 0) > 0 ? "+" : ""}
              {(stats.net_pnl || 0).toLocaleString()}
            </p>
            <span className="text-xl font-black text-purple-700">฿</span>
          </div>
          <p className="text-[10px] text-purple-800/60 font-black mt-1 uppercase tracking-tighter bg-purple-200/50 inline-block px-1 rounded">
            Based on closed positions
          </p>
        </div>
      </div>

      {/* 🟢 Card 2: Win Rate */}
      <div className="group bg-gradient-to-br from-emerald-50 to-white p-6 rounded-[24px] border-2 border-emerald-300 hover:border-emerald-500 shadow-lg transition-all duration-500 hover:-translate-y-1.5">
        <div className="flex items-center gap-2 mb-4 relative z-10">
          <div className="w-8 h-8 rounded-xl bg-white flex items-center justify-center text-emerald-600 border border-emerald-100 shadow-sm">
            <TrendingUp size={16} />
          </div>
          <h3 className="text-xs font-black text-emerald-800/60 uppercase tracking-widest">Win Rate</h3>
        </div>
        <div className="relative z-10">
          <div className="flex items-baseline gap-1.5">
            <p className="text-4xl font-black text-emerald-600 tracking-tight">
              {(stats?.win_rate ?? 0).toFixed(1)}
            </p>
            <span className="text-xl font-bold text-emerald-500">%</span>
          </div>
          <div className="w-full h-2 bg-emerald-100/50 rounded-full mt-3 overflow-hidden border border-emerald-100">
            <div
              className="h-full bg-gradient-to-r from-emerald-400 to-emerald-500 transition-all duration-1000"
              style={{ width: `${stats?.win_rate ?? 0}%` }}
            />
          </div>
        </div>
      </div>

      {/* 🔵 Card 3: Total Signals */}
      <div className="group bg-gradient-to-br from-blue-50 via-white to-indigo-50/50 p-6 rounded-[24px] border-2 border-blue-200 hover:border-blue-400 shadow-lg transition-all duration-500 hover:-translate-y-1.5">
        <div className="flex items-center justify-between mb-4 relative z-10">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-white flex items-center justify-center text-blue-600 border border-blue-100 shadow-sm">
              <Target size={16} />
            </div>
            <h3 className="text-xs font-black text-blue-900/60 uppercase tracking-widest">Total Signals</h3>
          </div>
          <span className="flex items-center gap-1.5 text-[10px] text-emerald-600 bg-white px-2.5 py-1 rounded-lg border border-emerald-100 font-bold uppercase tracking-wider shadow-sm">
            <span
              className={`w-1.5 h-1.5 rounded-full bg-emerald-500 ${stats.active_signals > 0 ? "animate-pulse" : ""}`}
            />
            {stats.active_signals} Active
          </span>
        </div>
        <div className="relative z-10">
          <p className="text-4xl font-black text-gray-900 tracking-tight">
            {stats?.total_signals ?? 0}
          </p>
          <div className="flex items-center gap-1 mt-1">
            <span className="text-[10px] text-blue-600 font-black px-1.5 py-0.5 bg-blue-100/50 rounded-md">
              +{stats.weekly_growth}
            </span>
            <span className="text-[10px] text-gray-400 font-bold uppercase tracking-tighter">
              signals this week
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
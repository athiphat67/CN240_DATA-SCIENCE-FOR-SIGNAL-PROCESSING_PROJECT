import React, { useState, useEffect } from "react";
import { Activity, Brain, Target } from "lucide-react";

export const SignalAnalytics = () => {
  const [analytics, setAnalytics] = useState({
    avg_pnl: "+0.00%",
    avg_confidence: "0.0%",
    total_trades: "0",
  });

  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        const response = await fetch(
          `${import.meta.env.VITE_API_URL}/api/signal-analytics`,
        );
        if (response.ok) {
          const data = await response.json();
          setAnalytics({
            avg_pnl: `${(data.avg_pnl || 0) > 0 ? "+" : ""}${(data.avg_pnl || 0).toFixed(2)}%`,
            avg_confidence: `${((data.avg_confidence || 0) * 100).toFixed(1)}%`,
            total_trades: (data.total_trades || 0).toString(),
          });
        }
      } catch (error) {
        console.error("Error fetching analytics:", error);
      }
    };
    fetchAnalytics();
  }, []);

  const stats = [
    {
      label: "Average P&L per Trade",
      value: analytics.avg_pnl,
      desc: "Mean return across all trades",
      icon: Activity,
      color: "text-[#824199]",
      borderColor: "border-purple-100",
      ringColor: "ring-purple-50/50",
      bg: "bg-purple-50/50",
    },
    {
      label: "AI Avg. Confidence",
      value: analytics.avg_confidence,
      desc: "Historical prediction certainty",
      icon: Brain,
      color: "text-emerald-600",
      borderColor: "border-emerald-100",
      ringColor: "ring-emerald-50/50",
      bg: "bg-emerald-50/50",
    },
    {
      label: "Total Executed Trades",
      value: analytics.total_trades,
      desc: "Total BUY and SELL recorded",
      icon: Target,
      color: "text-blue-600",
      borderColor: "border-blue-100",
      ringColor: "ring-blue-50/50",
      bg: "bg-blue-50/50",
    },
  ];

  return (
    <div className="relative mb-12 font-sans">
      <div className="absolute -top-6 left-1/2 -translate-x-1/2 w-[95%] h-6 border-x-2 border-t-2 border-dashed border-gray-200 rounded-t-[32px] opacity-30 pointer-events-none" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 relative z-10">
        {stats.map((item, i) => (
          <div
            key={i}
            className={`bg-white p-5 rounded-[24px] border-2 ${item.borderColor} ring-4 ${item.ringColor} shadow-lg flex items-center gap-4 hover:-translate-y-1 transition-all duration-300 group`}
          >
            <div
              className={`w-14 h-14 ${item.bg} ${item.color} rounded-2xl flex items-center justify-center shrink-0 border border-white shadow-inner group-hover:scale-110 transition-transform`}
            >
              <item.icon size={24} strokeWidth={2.5} />
            </div>
            <div className="flex-1">
              <div className="flex justify-between items-start mb-0.5">
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest">
                  {item.label}
                </p>
                <div
                  className={`w-1.5 h-1.5 rounded-full ${item.color.replace("text-", "bg-")} opacity-40 animate-pulse`}
                />
              </div>
              <p className="text-xl font-black text-gray-900 leading-tight mb-1">
                {item.value}
              </p>
              <p className="text-[10px] text-gray-500 font-bold uppercase tracking-tighter opacity-70">
                {item.desc}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

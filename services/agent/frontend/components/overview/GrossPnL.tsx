import React, { useEffect, useState } from "react";
import {
  TrendingUp,
  Globe,
  RefreshCcw,
  ArrowUpRight,
  ArrowDownLeft,
  Clock,
  BarChart3,
  Activity,
} from "lucide-react";

interface GoldData {
  hsh_sell?: number;
  hsh_buy?: number;
  spot_price?: number;
  usd_thb?: number;
}

interface MarketState {
  spot_price?: number;
  ask_96?: number;
  bid_96?: number;
  rsi_14?: number;
  trend?: string;
  macd_hist?: number;
  ema_20?: number;
  ema_50?: number;
  bollinger_upper?: number;
  timestamp?: string;
}

export const GrossPnL = () => {
  const [goldData, setGoldData] = useState<GoldData | null>(null);
  const [marketState, setMarketState] = useState<MarketState | null>(null);
  const [loading, setLoading] = useState(true);
  // 💡 เพิ่ม State เก็บเวลาที่อัปเดตข้อมูลล่าสุด
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const isUp = marketState?.trend?.toUpperCase() === "UPTREND";

  const fetchData = async () => {
    setLoading(true);
    try {
      // 1. ดึง URL มาจาก Environment (ถ้าหาไม่เจอ ให้ใช้ localhost เป็นค่าสำรอง)
      const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

      // 2. ใช้ Template Literal (เครื่องหมาย ` `) เพื่อต่อ URL
      const [res1, res2] = await Promise.all([
        fetch(`${API_URL}/api/gold-prices`),
        fetch(`${API_URL}/api/market-state`),
      ]);

      if (res1.ok) setGoldData(await res1.json());
      if (res2.ok) setMarketState(await res2.json());

      // 💡 เมื่อดึงข้อมูลสำเร็จ ให้บันทึกเวลาปัจจุบัน
      setLastUpdated(new Date());
    } catch (error) {
      console.error("Fetch Error:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); // อัปเดตทุก 1 นาที
    return () => clearInterval(interval);
  }, []);

  const spread =
    marketState?.ask_96 && marketState?.bid_96
      ? marketState.ask_96 - marketState.bid_96
      : 0;

  // 💡 ฟังก์ชันจัดการ Format เวลา
  const formatTime = (date: Date | null) => {
    if (!date) return "--:--:--";
    return date.toLocaleTimeString("th-TH", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  return (
    <div className="flex flex-col gap-4 h-full font-sans">
      {/* 🔄 1. Market Snapshot */}
      <div className="flex-1 rounded-[24px] p-6 shadow-2xl border border-[#824199]/40 bg-gradient-to-br from-[#1e102a] via-[#3d1a5a] to-[#36174d] flex flex-col justify-center relative overflow-hidden font-sans">
        <div className="absolute -top-10 -right-5 w-48 h-48 bg-[#824199]/20 rounded-full blur-[80px] pointer-events-none" />

        <div className="relative z-10 flex items-center justify-between mb-6">
          <div className="flex flex-col">
            <h2 className="text-xs font-bold text-purple-300/80 uppercase tracking-[0.2em] mb-1">
              Hua Seng Heng
            </h2>
            <h2 className="text-[15px] font-black text-white uppercase tracking-widest flex items-center gap-2">
              <Globe size={16} className="text-purple-400" /> Market Snapshot
            </h2>
          </div>

          {/* 💡 เพิ่มเวลาอัปเดตข้างปุ่ม Refresh */}
          <div className="flex items-center gap-3">
            <div className="flex flex-col items-end hidden sm:flex">
              <span className="text-[9px] text-purple-300/50 uppercase tracking-widest font-bold">
                Last Updated
              </span>
              <span className="text-xs font-mono text-purple-200/80">
                {formatTime(lastUpdated)}
              </span>
            </div>
            <button
              onClick={fetchData}
              className={`bg-white/10 p-2.5 rounded-xl text-white hover:bg-white/20 transition-all active:scale-95 ${loading ? "opacity-50" : ""}`}
              title="Refresh Data"
            >
              <RefreshCcw size={16} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        <div className="relative z-10 my-auto grid grid-cols-2 gap-4">
          {/* HSH SELL */}
          <div className="bg-white/10 border border-white/10 rounded-2xl p-4 backdrop-blur-md">
            <p className="text-[11px] text-purple-200 font-bold mb-2 uppercase tracking-widest flex items-center gap-1.5">
              <ArrowUpRight size={14} className="text-rose-400" /> HSH Sell
            </p>
            <p className="text-[28px] font-bold text-white tracking-normal">
              {goldData?.hsh_sell?.toLocaleString() || "---"}
            </p>
          </div>
          {/* HSH BUY */}
          <div className="bg-white/5 border border-white/10 rounded-2xl p-4 backdrop-blur-md">
            <p className="text-[11px] text-purple-200 font-bold mb-2 uppercase tracking-widest flex items-center gap-1.5">
              <ArrowDownLeft size={14} className="text-emerald-400" /> HSH Buy
            </p>
            <p className="text-[28px] font-bold text-white tracking-normal">
              {goldData?.hsh_buy?.toLocaleString() || "---"}
            </p>
          </div>
        </div>

        <div className="relative z-10 mt-6 grid grid-cols-2 gap-4 bg-black/20 p-3.5 rounded-xl border border-white/5">
          <div className="flex flex-col">
            <span className="text-[10px] font-bold text-purple-200/70 uppercase tracking-widest mb-1">
              Spot (XAU/USD)
            </span>
            <span className="text-[15px] font-bold text-white tracking-wide">
              ${goldData?.spot_price?.toLocaleString() || "---"}
            </span>
          </div>
          <div className="flex flex-col border-l border-white/10 pl-4">
            <span className="text-[10px] font-bold text-purple-200/70 uppercase tracking-widest mb-1">
              USD/THB
            </span>
            <span className="text-[15px] font-bold text-white tracking-wide">
              {goldData?.usd_thb?.toFixed(2) || "---"}
            </span>
          </div>
        </div>
      </div>

      {/* 🔄 2. MARKET STATE */}
      <div className="flex-1 bg-white rounded-[24px] p-6 shadow-[0_25px_60px_-15px_rgba(0,0,0,0.1)] flex flex-col border-2 border-purple-200">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[14px] font-black text-gray-900 uppercase tracking-widest flex items-center gap-2">
            <Activity size={18} className="text-[#824199]" /> Market State
          </h2>
          <div
            className="flex items-center gap-1.5 text-[10px] font-bold text-gray-500 bg-gray-100 px-2.5 py-1 rounded-lg border border-gray-200 shadow-sm"
            title="Server Timestamp"
          >
            <Clock size={12} className="text-gray-400" />
            {marketState?.timestamp
              ? new Date(marketState.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "--:--"}
          </div>
        </div>

        <div className="space-y-4">
          <div className="bg-gray-50/80 rounded-xl p-3 border border-gray-100">
            <div className="flex justify-between items-end mb-2">
              <span className="text-[10px] font-bold text-gray-400">
                Gold (USD)
              </span>
              <span className="text-sm font-black text-[#824199]">
                ${marketState?.spot_price?.toFixed(2) || "---"}
              </span>
            </div>
            <div className="flex justify-between items-center pt-2 border-t border-gray-200/50">
              <div className="flex flex-col">
                <span className="text-[9px] font-bold text-emerald-600">
                  BUY NOW
                </span>
                <span className="text-[15px] font-black text-gray-900">
                  ฿{marketState?.bid_96?.toLocaleString() || "---"}
                </span>
              </div>
              <div className="flex flex-col items-end">
                <span className="text-[9px] font-bold text-rose-500">
                  SELL NOW
                </span>
                <span className="text-[15px] font-black text-gray-900">
                  ฿{marketState?.ask_96?.toLocaleString() || "---"}
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="bg-rose-50/50 border border-rose-100 rounded-xl p-3">
              <span className="text-[9px] font-bold text-rose-400 block mb-1">
                RSI(14)
              </span>
              <div className="flex items-center gap-2">
                <span className="text-lg font-black text-rose-600">
                  {marketState?.rsi_14 ?? "---"}
                </span>
                <span className="text-[8px] bg-rose-600 text-white px-1.5 py-0.5 rounded font-black">
                  {marketState?.rsi_14 && marketState.rsi_14 < 30
                    ? "OVERSOLD"
                    : "NEUTRAL"}
                </span>
              </div>
            </div>
            <div
              className={`rounded-xl p-3 border ${isUp ? "bg-emerald-50/50 border-emerald-100" : "bg-rose-50/50 border-rose-100"}`}
            >
              <span
                className={`text-[9px] font-bold block mb-1 ${isUp ? "text-emerald-400" : "text-rose-400"}`}
              >
                Trend
              </span>
              <div className="flex items-center gap-2">
                {/* เปลี่ยนไอคอนตาม Trend */}
                {isUp ? (
                  <TrendingUp size={14} className="text-emerald-600" />
                ) : (
                  <ArrowDownLeft size={14} className="text-rose-600" />
                )}

                <span
                  className={`text-[12px] font-black uppercase ${isUp ? "text-emerald-700" : "text-rose-700"}`}
                >
                  {marketState?.trend || "N/A"}
                </span>
              </div>
            </div>
          </div>

          <div className="bg-white border-2 border-gray-50 rounded-xl p-3 shadow-sm">
            <div className="flex items-center gap-2 mb-2">
              <BarChart3 size={14} className="text-purple-400" />
              <span className="text-[10px] font-black text-gray-400 uppercase">
                Indicator Details
              </span>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-[11px]">
                <span className="text-gray-400">MACD Hist</span>
                <span className="text-rose-500 font-bold">
                  {marketState?.macd_hist?.toFixed(4) || "---"}
                </span>
              </div>
              <div className="flex justify-between text-[11px]">
                <span className="text-gray-400">EMA 20/50</span>
                <span className="text-gray-700 font-bold">
                  {marketState?.ema_20 || "-"} / {marketState?.ema_50 || "-"}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 💡 เปลี่ยน Snapshot Date ด้านล่างเป็นเวลา Last Sync แบบชัดเจน */}
        <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between opacity-60">
          <span className="text-[9px] font-bold text-gray-400">
            Spread ≈ {spread.toFixed(1)} THB
          </span>
          <span className="text-[9px] font-mono text-gray-400 flex items-center gap-1">
            <RefreshCcw size={10} className={loading ? "animate-spin" : ""} />
            Last sync: {formatTime(lastUpdated)}
          </span>
        </div>
      </div>
    </div>
  );
};

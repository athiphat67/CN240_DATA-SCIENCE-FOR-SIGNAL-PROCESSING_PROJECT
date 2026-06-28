import React, { useState, useEffect } from "react";
import { Search, Zap } from "lucide-react"; // 💡 เพิ่ม Import Zap (ไอคอนสายฟ้า)
import { useNavigate, useLocation } from "react-router-dom";
import { NotificationDropdown } from "../NotificationDropdown";

export const OverviewHeader = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const formattedDate = currentTime.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
  const formattedTime = currentTime.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  // 💡 1. เอา AI Analysis ออกจาก Array นี้ เพื่อไม่ให้มันเป็นแค่ขีดเส้นใต้ธรรมดา
  const navTabs = [
    { name: "Overview", path: "/overview" },
    { name: "Signals", path: "/signals" },
    { name: "Market", path: "/market" },
    { name: "Portfolio", path: "/portfolio" },
    { name: "History", path: "/history" },
    { name: "BackTest", path: "/backtest" },
  ];

  // 💡 ฟังก์ชันสำหรับกำหนดคำทักทายตามชั่วโมงปัจจุบัน (0-23)
  const getGreeting = () => {
    const currentHour = currentTime.getHours();

    if (currentHour < 12) {
      return "Good Morning,";
    } else if (currentHour < 18) {
      return "Good Afternoon,";
    } else {
      return "Good Evening,";
    }
  };

  const greetingMessage = getGreeting();

  return (
    <div
      className="relative pt-6 z-[100] flex flex-col justify-between"
      style={{
        background:
          "linear-gradient(135deg, #1a0a24 0%, #2d1040 40%, #1a0a24 100%)",
      }}
    >
      {/* Background Silk Waves */}
      <div className="absolute inset-0 overflow-hidden opacity-40 pointer-events-none">
        <svg
          viewBox="0 0 700 200"
          preserveAspectRatio="none"
          className="w-full h-full"
        >
          <path
            d="M0 60 Q200 10 400 90 T700 40"
            stroke="#ffffff15"
            strokeWidth="1.5"
            fill="none"
          />
          <path
            d="M0 110 Q220 50 420 130 T700 90"
            stroke="#f9d44315"
            strokeWidth="1.5"
            fill="none"
          />
        </svg>
      </div>

      <div className="relative z-10 px-8">
        {/* Top Bar */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex flex-col md:flex-row md:items-center gap-1 md:gap-4">
            <p className="font-['Newsreader'] font-light text-white/40 text-[12px] md:text-sm tracking-[0.05em]">
              {formattedDate}
            </p>
            <span className="hidden md:block w-1 h-1 bg-white/20 rounded-full" />
            <p className="font-mono text-[#f9d443] text-[12px] md:text-sm opacity-80 tracking-widest">
              {formattedTime}{" "}
              <span className="text-[10px] ml-1 opacity-50 font-sans">
                UTC +7
              </span>
            </p>
          </div>

          <div className="flex items-center gap-4 font-sans">
            <div className="hidden md:flex items-center gap-2 bg-white/5 border border-white/10 px-3 py-2 rounded-xl backdrop-blur-md">
              <Search size={14} className="text-white/40" />
              <input
                type="text"
                placeholder="Search signal ID..."
                className="bg-transparent text-[13px] text-white outline-none w-40 placeholder:text-white/30"
              />
            </div>

            <NotificationDropdown />

            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-yellow-400 to-orange-500 flex items-center justify-center font-bold text-[#1a0a24] text-xs shadow-lg border border-yellow-300/50">
              NA
            </div>
          </div>
        </div>

        {/* Greeting Section */}
        <div className="mb-6 mt-1">
          <h1 className="font-['Newsreader'] text-4xl md:text-5xl text-white/90 leading-tight tracking-tight flex flex-wrap items-baseline gap-x-2.5">
            {/* 💡 เปลี่ยนจุดนี้ให้รับค่าแบบ Dynamic */}
            <span>{greetingMessage}</span>
            <span className="italic text-[#f9d443] font-normal">
              NAKKHUTTHONG
            </span>
            <span>Agent.</span>
          </h1>
          <p className="font-['Newsreader'] italic text-white/40 text-lg md:text-xl mt-1 tracking-wide font-light">
            Welcome back to your intelligence dashboard.
          </p>
        </div>

        {/* 💡 2. Navigation Tabs & Floating AI Button */}
        <nav className="flex items-center justify-between border-b border-white/5 w-full font-sans pb-4">
          {/* ฝั่งซ้าย: เมนูธรรมดา */}
          <div className="flex items-center gap-2 overflow-x-auto no-scrollbar bg-white/5 p-1 rounded-2xl border border-white/5">
            {navTabs.map((tab) => {
              const isActive = location.pathname.includes(tab.path);
              return (
                <button
                  key={tab.name}
                  onClick={() => navigate(tab.path)}
                  // ปรับ h-10 เพื่อให้ความสูงคงที่เท่ากับปุ่มขวา
                  className={`relative px-5 h-10 flex items-center justify-center text-sm md:text-base font-bold transition-all duration-500 rounded-xl whitespace-nowrap ${
                    isActive
                      ? "text-[#1a0a24] bg-[#f9d443] shadow-[0_4px_15px_rgba(249,212,67,0.2)]"
                      : "text-white/40 hover:text-white/70 hover:bg-white/5"
                  }`}
                >
                  <span className="relative z-10">{tab.name}</span>
                  {isActive && (
                    <div className="absolute inset-0 bg-gradient-to-tr from-white/20 to-transparent rounded-xl pointer-events-none" />
                  )}
                </button>
              );
            })}
          </div>

          {/* ฝั่งขวา: ปุ่ม AI Analysis */}
          <div className="pl-4">
            <button
              onClick={() => navigate("/agent-analysis")}
              // ใช้ h-10 เท่ากับฝั่งซ้าย และปรับ rounded-xl ให้เข้าพวก หรือมนกว่าเดิมนิดหน่อย
              className="relative inline-flex items-center justify-center px-6 h-10 text-sm font-bold text-[#1a0a24] bg-gradient-to-r from-[#f9d443] to-[#f9a826] rounded-xl shadow-[0_6px_20px_-4px_rgba(249,212,67,0.4)] hover:shadow-[0_10px_25px_-4px_rgba(249,212,67,0.6)] hover:-translate-y-0.5 transition-all duration-300 group overflow-hidden whitespace-nowrap"
            >
              <span className="absolute inset-0 w-full h-full bg-gradient-to-r from-transparent via-white/40 to-transparent -translate-x-full group-hover:animate-[shimmer_1.5s_infinite]"></span>

              <span className="relative flex items-center gap-2 tracking-tight">
                <Zap size={16} className="text-[#1a0a24] fill-[#1a0a24]" />
                Live AI Analysis
              </span>
            </button>
          </div>
        </nav>
      </div>
    </div>
  );
};

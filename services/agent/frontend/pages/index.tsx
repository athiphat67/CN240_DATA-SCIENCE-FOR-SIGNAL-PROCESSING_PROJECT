import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom'; // 1. เพิ่มชุดนี้เข้าไป
import Lenis from 'lenis';

// Import Components
import { Navbar } from "../components/Navbar";
import { HeroSection } from "../components/sections/HeroSection";
import { OverviewSection } from "../components/overview/OverviewSection";
import { GoldPortfolioInsightsSection } from "../components/sections/GoldPortfolioInsightsSection";
import { HowItWorksStepsSection } from "../components/sections/HowItWorksStepsSection";
import { TransparentRationaleSection } from "../components/sections/TransparentRationaleSection";
import { CommonQuestionsSection } from "../components/sections/CommonQuestionsSection";
import { GoldTradingCTASection } from "../components/sections/GoldTradingCTASection";
import { SignalDetail } from '../components/signals/SignalDetail';
import { SignalsSection } from '../components/signals/SignalsSection';
import { PortfolioSection } from '../components/portfolio/PortfolioSection';
import  HistorySection  from '../components/history/HistorySection';
import { MarketSnapshot } from '../components/market/MarketSection';
import { SettingsSection } from '../components/settings/SettingSection';
import { AnalyticsSection } from '../components/analytics/AnalyticSection';
import { BacktestSection } from '../components/backtest/BacktestSection';

import LiveAnalysis from '../components/Aiagent/LiveAnalysis';

// Styles
import "../styles/tailwind.css";


// --- 2. สร้าง Component แยกสำหรับหน้า Landing (หน้าหลักเดิม) ---
const LandingPage = () => {
  return (
    <>
      {/* ย้าย Navbar มาไว้เฉพาะในหน้านี้ */}
      <Navbar />

      <main className="flex flex-col items-center w-full">
        <div className="w-full pt-32 flex flex-col items-center">
          <HeroSection />
        </div>

        <div className="flex flex-col gap-32 w-full max-w-screen-xl mt-32">
          <GoldPortfolioInsightsSection />
          <HowItWorksStepsSection />
          <TransparentRationaleSection />
          <CommonQuestionsSection />
          <GoldTradingCTASection />
        </div>
      </main>
    </>
  );
};

// --- 3. ปรับโครงสร้าง MainAppContainer ให้มีระบบ Routing ---
export const MainAppContainer = () => {
  useEffect(() => {
    const lenis = new Lenis({
      duration: 1.5, // ลดเวลาลงนิดหน่อยให้หน้าใหม่ลื่นไหลขึ้น
      lerp: 0.05,
      smoothWheel: true,
    });

    (window as any).lenis = lenis;

    function raf(time: number) {
      lenis.raf(time);
      requestAnimationFrame(raf);
    }
    requestAnimationFrame(raf);

    return () => {
      lenis.destroy();
      (window as any).lenis = null;
    };
  }, []);

  return (
    <BrowserRouter>
      <div className="bg-premium-gradient min-h-screen text-slate-800 transition-colors duration-500"> 
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/overview" element={<OverviewSection />} />
          <Route path="/signals" element={<SignalsSection />} />
          <Route path="/signals/:id" element={<SignalDetail />} />
          <Route path="/portfolio" element={<PortfolioSection />} />
          <Route path="/history" element={<HistorySection />} />
          <Route path="/market" element={<MarketSnapshot />} />
          <Route path="/settings" element={<SettingsSection />} />
          <Route path="/backtest" element={<BacktestSection />} />
          <Route path="/agent-analysis" element={<LiveAnalysis />} />
        </Routes>

        <footer className="py-12 text-[#11182740] text-xs text-center">
          © 2026 NAKKHUTTHONG. All rights reserved.
        </footer>
      </div>
    </BrowserRouter>
  );
};

// Rendering
const rootElement = document.getElementById("root");
if (rootElement) {
  const root = createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <MainAppContainer />
    </React.StrictMode>
  );
}
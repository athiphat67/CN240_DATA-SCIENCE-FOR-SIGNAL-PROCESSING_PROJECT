import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

// 1. นำเข้าหน้า Overview จากโฟลเดอร์ overview
import { OverviewSection } from './components/overview/OverviewSection';

// 2. นำเข้าหน้า Signals และ Detail จากโฟลเดอร์ signals
import { SignalsSection } from './components/signals/SignalsSection';
import { SignalDetail } from './components/signals/SignalDetail';
import { PortfolioSection } from './components/portfolio/PortfolioSection';
import { HistorySection } from './components/history/HistorySection';
import { MarketSnapshot } from './components/market/MarketSection';
import { SettingsSection } from './components/settings/SettingSection'
import { BacktestSection } from './components/backtest/BacktestSection'
import LiveAnalysis from '../components/Aiagent/LiveAnalysis';


function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/overview" replace />} />
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
    </BrowserRouter>
  );
}

export default App;
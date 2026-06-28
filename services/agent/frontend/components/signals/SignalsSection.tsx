import React, { useState, useEffect } from 'react';
import { OverviewHeader } from '../overview/OverviewHeader'; 
import { SignalsHeader } from './SignalsHeader';
import { SignalStatsCards } from './SignalStatsCards';
import { SignalAnalytics } from './SignalAnalytics'; 
import { SignalPerformanceChart } from './SignalPerformanceChart'; 
import { SignalFilterBar } from './SignalFilterBar';
import { SignalMasterTable, SignalLog } from './SignalMasterTable'; // อิมพอร์ต Interface มาด้วย

export const SignalsSection = () => {
  const [activeFilter, setActiveFilter] = useState('All');
  const [signals, setSignals] = useState<SignalLog[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // 1. ดึงข้อมูล API ที่นี่จุดเดียว เพื่อกระจายให้ทุก Component ในหน้านี้
  useEffect(() => {
    const fetchLogs = async () => {
      setIsLoading(true);
      try {
        // แนะนำให้ดึงจำนวนเยอะหน่อยเพื่อเอาไปวาดกราฟได้ด้วย (เช่น 50 รายการ)
        const response = await fetch(`${import.meta.env.VITE_API_URL}/api/recent-signals?limit=50`);
        if (response.ok) {
          const data = await response.json();
          setSignals(data);
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
  }, []);

  // 2. กรองข้อมูลตามที่กดใน Filter Bar ('All', 'BUY', 'SELL', 'HOLD')
  const filteredSignals = activeFilter === 'All' 
    ? signals 
    : signals.filter(s => s.signal === activeFilter);

  return (
    <section className="w-full min-h-screen pb-12" style={{ background: '#FCFBF7' }}>
      <OverviewHeader /> 

      <div className="px-6 mt-8 relative z-20 max-w-7xl mx-auto">
        <SignalsHeader />
        <SignalStatsCards />
        <SignalAnalytics />
        
        {/* ในอนาคตคุณสามารถส่ง signals={signals} ไปให้ Chart วาดกราฟได้ด้วย */}
        <SignalPerformanceChart />

        <div className="mt-12 mb-6">
            <h2 className="text-xl font-black text-gray-900 mb-2">Signals Master Log</h2>
            <p className="text-sm text-gray-400 font-medium">Full archive of agent signals with complete rationale tracing.</p>
        </div>
        
        <SignalFilterBar activeFilter={activeFilter} setActiveFilter={setActiveFilter} />
        
        {/* 3. ส่งข้อมูลที่ผ่านการกรองแล้วและสถานะ Loading ให้ตาราง */}
        <SignalMasterTable signals={filteredSignals} isLoading={isLoading} />
      </div>
    </section>
  );
};
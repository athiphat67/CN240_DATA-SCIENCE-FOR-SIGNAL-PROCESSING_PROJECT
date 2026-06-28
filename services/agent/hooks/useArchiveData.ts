import { useState, useEffect } from 'react';
import { ArchiveSummary, TradeRecord } from '../types/archive';

export const useArchiveData = () => {
  const [summary, setSummary] = useState<ArchiveSummary | null>(null);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [signals, setSignals] = useState<any[]>([]); // เพิ่มเพื่อแก้ตัวแดงใน HistorySection
  const [logs, setLogs] = useState<any[]>([]);     // เพิ่มเพื่อแก้ตัวแดงใน HistorySection
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchArchive = async () => {
      try {
        setIsLoading(true);
        const response = await fetch('http://localhost:8000/api/archive/history');
        const result = await response.json();

        if (result.status === "success") {
          setSummary(result.summary);
          setTrades(result.trades);
          // ปัจจุบัน API ส่งมาแค่ trades ถ้าต้องการ signals/logs ต้องเพิ่ม Endpoint ใน Python
          setSignals([]); 
          setLogs([]);
        }
      } catch (error) {
        console.error("Archive fetch error:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchArchive();
  }, []);

  return { summary, trades, signals, logs, isLoading };
};
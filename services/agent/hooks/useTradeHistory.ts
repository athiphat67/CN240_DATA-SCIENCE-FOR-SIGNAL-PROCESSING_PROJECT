import { useState, useEffect } from 'react';
import { ArchiveSummary, TradeRecord } from '../types/history';

export const useTradeHistory = () => {
  const [summary, setSummary] = useState<ArchiveSummary | null>(null);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        setIsLoading(true);
        const response = await fetch('http://localhost:8000/api/archive/history');
        const result = await response.json();

        if (result.status === "success") {
          setSummary(result.summary);
          setTrades(result.trades);
        }
      } catch (error) {
        console.error("Failed to fetch history:", error);
      } finally {
        setIsLoading(false);
      }
    };

    fetchHistory();
  }, []);

  return { summary, trades, isLoading };
};
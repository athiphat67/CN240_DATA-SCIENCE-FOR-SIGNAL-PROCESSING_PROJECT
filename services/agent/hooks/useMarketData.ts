import { useState, useEffect } from 'react';

export const useMarketData = () => {
  const [ohlcData, setOhlcData] = useState<any[]>([]);
  const [usdThbData, setUsdThbData] = useState<any[]>([]);
  const [techData, setTechData] = useState<any[]>([]);
  const [currentStats, setCurrentStats] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [timeframe, setTimeframe] = useState('4H');

  useEffect(() => {
    const fetchMarket = async () => {
      try {
        setIsLoading(true);
        // Ensure the port matches your FastAPI server (default is 8000)
        const response = await fetch(`http://localhost:8000/api/market/data?timeframe=${timeframe}`);
        const result = await response.json();

        if (result.status === "success" && result.data) {
          // 1. Map OHLC for Candlestick Chart
          const ohlc = result.data.map((item: any) => ({
            x: new Date(item.run_at).getTime(),
            y: [item.gold_price_thb, item.gold_price_thb + 10, item.gold_price_thb - 10, item.gold_price_thb]
          }));

          // 2. Map USD/THB for Line Chart
          const fx = result.data.map((item: any) => ({
            x: new Date(item.run_at).getTime(),
            y: item.usd_thb_rate || 0
          }));

          // 3. Map Technicals (RSI, MACD, BB, ATR)
          const tech = result.data.map((item: any) => ({
            x: new Date(item.run_at).getTime(),
            rsi: item.rsi || 0,
            macd_line: item.macd_line || 0,
            macd_hist: item.macd_histogram || 0,
            bb_pct_b: item.bb_pct_b || 0,
            atr_thb: item.atr_thb || 0,
            confidence: item.confidence || 0,
            ai_signal: item.signal || 'HOLD'
          }));

          setOhlcData(ohlc);
          setUsdThbData(fx);
          setTechData(tech);
          
          if (result.data.length > 0) {
            const latest = result.data[0];
            setCurrentStats({
              current_thb: latest.gold_price_thb || 0,
              current_usd: latest.gold_price || 0,
              usd_thb: latest.usd_thb_rate || 0,
              trend: latest.signal || 'NEUTRAL'
            });
          }
        }
      } catch (error) {
        console.error("Fetch error:", error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchMarket();
  }, [timeframe]);

  return { ohlcData, usdThbData, techData, currentStats, isLoading, timeframe, setTimeframe };
};
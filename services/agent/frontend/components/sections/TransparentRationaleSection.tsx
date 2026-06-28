import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Terminal, BarChart3 } from 'lucide-react';

const rationaleData = [
  { id: 1, signal: "BUY", confidence: "85%", color: "#10b981", text: "Technicals confirm strong upward momentum. RSI has entered the oversold territory (< 35), and MACD exhibits a clear bullish divergence.", indicators: ["Technical: Oversold", "Momentum: MACD Bullish", "Fed Policy: Favorable"] },
  { id: 2, signal: "HOLD", confidence: "62%", color: "#f59e0b", text: "Market is currently consolidating near major resistance levels. Waiting for a clear breakout above $2,350 before increasing position size.", indicators: ["Resistance: $2,350", "Volume: Decreasing", "Volatility: High"] },
  { id: 3, signal: "SELL", confidence: "78%", color: "#ef4444", text: "Bearish engulfing pattern detected on daily timeframe. Significant profit taking observed following the recent non-farm payroll data.", indicators: ["Pattern: Bearish Engulfing", "Data: NFP Strong", "Trend: Overextended"] }
];

export const TransparentRationaleSection = () => {
  const [index, setIndex] = useState(0);
  const [isHovered, setIsHovered] = useState(false); 

  const updateIndex = (newIndex: number) => setIndex((newIndex + rationaleData.length) % rationaleData.length);

  useEffect(() => {
    if (isHovered) return; 
    const interval = setInterval(() => updateIndex(index + 1), 3500); 
    return () => clearInterval(interval); 
  }, [index, isHovered]); 

  const getActiveStyle = (signal: string) => {
    switch(signal) {
        case 'BUY': return 'bg-gradient-to-br from-[#2d103b] via-[#4d235e] to-[#824199] shadow-[0_25px_60px_rgba(130,65,153,0.3)] border-[#824199]/50 text-white';
        case 'HOLD': return 'bg-gradient-to-br from-[#160620] to-[#2d103b] shadow-[0_25px_60px_rgba(130,65,153,0.1)] border-[#824199]/30 text-white';
        case 'SELL': return 'bg-gradient-to-br from-[#3b082c] to-[#6b154a] shadow-[0_25px_60px_rgba(239,68,68,0.2)] border-[#ef4444]/50 text-white';
        default: return 'bg-[#1a0a24] border-[#824199]/20 text-white';
    }
  };

  const getGlowStyle = (signal: string) => {
    switch(signal) {
        case 'BUY': return 'bg-[#824199]/40'; 
        case 'HOLD': return 'bg-[#824199]/10'; 
        case 'SELL': return 'bg-[#ef4444]/30'; 
        default: return 'bg-[#824199]/20';
    }
  };

  return (
    <section id="performance" className="relative flex flex-col items-center w-full py-24 px-8 bg-transparent scroll-mt-24 z-0 overflow-x-clip overflow-y-visible">
      
      <motion.div animate={{ scale: [1, 1.1, 1], opacity: [0.03, 0.06, 0.03] }} transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }} className="absolute top-1/2 left-[10%] w-[600px] h-[600px] bg-[#824199] rounded-full blur-[120px] pointer-events-none -z-10" />

      <div className="max-w-screen-xl w-full flex flex-col items-center gap-16 relative z-10">
        <div className="flex flex-col items-center gap-4 text-center">
          <h2 className="font-['Newsreader'] font-normal text-gray-900 text-5xl tracking-tight leading-tight">
            Transparent Rationale
          </h2>
          <p className="text-[#11182780] text-base font-normal">
            AI ของเราไม่ได้แค่ส่งสัญญาณ (Signal) ให้คุณ แต่เรายัง "คิดให้คุณ" ดูด้วย
          </p>
        </div>

        <div className="relative w-full flex items-center justify-center h-[550px]" onMouseEnter={() => setIsHovered(true)} onMouseLeave={() => setIsHovered(false)}>
          <div className="relative w-full max-w-4xl flex items-center justify-center">
            <AnimatePresence initial={false}>
              {rationaleData.map((card, i) => {
                let position = i - index;
                if (position < -1) position += rationaleData.length;
                if (position > 1) position -= rationaleData.length;
                if (![0, -1, 1].includes(position)) return null;

                const isCenter = position === 0;
                const activeStyle = getActiveStyle(card.signal);
                const glowStyle = getGlowStyle(card.signal);

                return (
                  <motion.div
                    key={card.id}
                    animate={{ x: position * 350, scale: isCenter ? 1 : 0.82, opacity: isCenter ? 1 : 0.35, zIndex: isCenter ? 30 : 10, rotateY: position * 15 }}
                    transition={{ type: "spring", stiffness: 200, damping: 25 }}
                    onClick={() => updateIndex(i)}
                    className={`absolute w-full max-w-3xl rounded-[40px] p-10 md:p-12 border-[1.5px] cursor-pointer overflow-hidden transition-colors duration-700 ${isCenter ? activeStyle : 'bg-white/90 backdrop-blur-2xl shadow-[0_25px_60px_rgba(0,0,0,0.05)] border-[#824199]/10 text-gray-900'}`}
                  >
                    {isCenter && <div className={`absolute -top-20 -right-20 w-80 h-80 rounded-full blur-[80px] pointer-events-none transition-colors duration-700 ${glowStyle}`} />}
                    <div className="absolute top-8 right-8 text-[#824199]/10 pointer-events-none"><BarChart3 size={40} /></div>

                    <div className="flex flex-col gap-10 relative z-10">
                      <div className="flex items-center justify-between gap-8">
                        <div className="flex items-center gap-6">
                          <div className="text-white px-8 py-3 rounded-2xl text-xl font-bold shadow-[0_20px_60px_rgba(130,65,153,0.06)]" style={{ backgroundColor: card.color }}>{card.signal}</div>
                          <div className="flex flex-col text-left">
                            <span className={`text-[10px] font-bold tracking-[0.15em] uppercase ${isCenter ? 'text-purple-200/60' : 'text-[#11182766]'}`}>Provider : AI</span>
                            <span className={`text-xl font-semibold uppercase ${isCenter ? 'text-white' : 'text-gray-900'}`}>Thai Gold 96.5%</span>
                          </div>
                        </div>
                        <div className="flex flex-col items-end">
                          <span className={`text-[10px] font-bold tracking-[0.15em] uppercase text-right ${isCenter ? 'text-purple-200/60' : 'text-[#11182766]'}`}>Confidence Score</span>
                          <span className={`font-['Newsreader'] font-semibold text-5xl ${isCenter ? 'text-[#f9d443]' : 'text-[#824199]'}`}>{card.confidence}</span>
                        </div>
                      </div>

                      <div className={`rounded-3xl p-8 flex flex-col gap-6 text-left border ${isCenter ? 'bg-[#00000040] backdrop-blur-md border-white/5 shadow-inner' : 'bg-[#11182703] border-[#1118270d]'}`}>
                        <div className="flex items-center gap-3">
                          <Terminal size={18} className={isCenter ? 'text-[#f9d443]' : 'text-[#824199]'} />
                          <span className={`text-xs font-bold tracking-[0.1em] uppercase ${isCenter ? 'text-gray-300' : 'text-gray-900'}`}>AI Agent Reasoning System</span>
                        </div>
                        <div className="flex flex-col gap-6">
                          <p className={`font-['Newsreader'] text-2xl leading-[1.6] italic ${isCenter ? 'text-gray-50' : 'text-gray-800'}`}>"{card.text}"</p>
                          <div className={`pt-6 border-t grid grid-cols-1 md:grid-cols-3 gap-4 ${isCenter ? 'border-white/10' : 'border-gray-200'}`}>
                            {card.indicators.map((ind, idx) => (
                              <div key={idx} className="flex items-center gap-3">
                                <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: card.color }} />
                                <span className={`text-[11px] font-medium ${isCenter ? 'text-gray-300' : 'text-[#11182780]'}`}>{ind}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        </div>

        <div className="flex gap-2 -mt-4">
          {rationaleData.map((_, i) => (
            <button key={i} onClick={() => updateIndex(i)} className={`w-2 h-2 rounded-full transition-all duration-300 ${i === index ? "w-8 bg-[#824199]" : "bg-gray-200"}`} />
          ))}
        </div>
      </div>
    </section>
  );
};
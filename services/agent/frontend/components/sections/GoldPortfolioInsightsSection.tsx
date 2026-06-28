import React from 'react';
import { motion } from 'framer-motion';
import { BrainCircuit, ShieldCheck, LineChart, Eye } from 'lucide-react';

const cards = [
  { icon: BrainCircuit, title: "Advanced\nReasoning", description: "ก้าวข้ามบอทตั้งเงื่อนไขทั่วไป สู่การวิเคราะห์ตลาดแบบองค์รวมด้วยความฉลาดของ LLM", },
  { icon: ShieldCheck, title: "Ironclad Risk\nManagement", description: "แนะนำจุด SL/TP อัตโนมัติตามค่าความผันผวนตลาด (ATR) พร้อมระบบคุมขีดจำกัดขาดทุนรายวัน", },
  { icon: LineChart, title: "Technical &\nFundamental", description: "ผสานสัญญาณเชิงเทคนิคเข้ากับการวิเคราะห์ Sentiment ข่าวเศรษฐกิจโลกแบบ Real-time", },
  { icon: Eye, title: "24/5 Vigilance", description: "เฝ้าระวังตลาดตลอดเวลาทำการ พร้อมระบบหลบหลีกช่วง Dead Zone เพื่อปกป้องเงินทุน", },
];

export const GoldPortfolioInsightsSection = () => {
  return (
    // ✨ ใช้ overflow-x-clip overflow-y-visible 
    <section id="features" className="relative flex flex-col items-center w-full py-24 px-8 bg-transparent scroll-mt-24 z-0 overflow-x-clip overflow-y-visible">
      
      <motion.div animate={{ scale: [1, 1.05, 1], opacity: [0.03, 0.05, 0.03] }} transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }} className="absolute top-1/2 left-[20%] w-[500px] h-[500px] bg-[#824199] rounded-full blur-[120px] pointer-events-none -z-10" />
      <motion.div animate={{ x: [0, -20, 0], y: [0, 20, 0], opacity: [0.04, 0.06, 0.04] }} transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }} className="absolute bottom-10 right-[10%] w-[400px] h-[400px] bg-[#f9d443] rounded-full blur-[100px] pointer-events-none -z-10" />

      <div className="max-w-screen-xl w-full flex flex-col gap-12 relative z-10">
        <div className="flex flex-col gap-4">
          <h2 className="font-['Newsreader'] font-normal text-gray-900 text-[56px] leading-[1.1] tracking-tight">
            Smarter decisions <br /> for <span className="italic text-[#824199]">gold</span> portfolio
          </h2>
          <p className="text-[#11182780] text-sm font-medium tracking-wide">
            Data-driven logic in every single trade.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {cards.map((card, index) => (
            <div 
              key={index} 
              className="group flex flex-col items-start p-8 bg-white/80 hover:bg-[#824199] backdrop-blur-xl rounded-[32px] border border-gray-100/50 hover:border-[#824199] shadow-[0_20px_50px_rgba(0,0,0,0.02)] hover:shadow-[0_30px_60px_rgba(130,65,153,0.25)] transition-all duration-500 hover:-translate-y-2 cursor-pointer"
            >
              <div className="w-12 h-12 bg-[#824199]/10 group-hover:bg-white rounded-2xl flex items-center justify-center mb-6 group-hover:scale-110 transition-all duration-500">
                <card.icon size={22} className="text-[#824199]" />
              </div>
              <h3 className="text-xl font-semibold text-gray-900 group-hover:text-white leading-tight mb-4 whitespace-pre-line transition-colors duration-500">
                {card.title}
              </h3>
              <p className="text-sm text-[#11182799] group-hover:text-white/80 leading-[1.6] font-normal transition-colors duration-500">
                {card.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
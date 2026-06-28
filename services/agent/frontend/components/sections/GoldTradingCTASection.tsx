import React from 'react';
import { motion } from 'framer-motion';
import { ArrowUpRight } from 'lucide-react';

export const GoldTradingCTASection = () => {
  const handleGoToOverview = () => window.location.href = '/overview';

  return (
    <section className="relative flex flex-col items-center w-full py-12 px-6 bg-transparent z-0 overflow-x-clip overflow-y-visible">
      
      <motion.div animate={{ scale: [1, 1.1, 1], opacity: [0.03, 0.06, 0.03] }} transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }} className="absolute top-1/2 left-[20%] w-[600px] h-[600px] bg-[#824199] rounded-full blur-[120px] pointer-events-none -z-10" />

      <div className="relative flex flex-col items-center w-full max-w-screen-xl bg-gradient-to-br from-[#0c0512] via-[#1a0a24] to-[#401360] rounded-[48px] p-16 md:p-24 overflow-hidden shadow-[0_24px_48px_rgba(26,10,36,0.25)] border border-[#824199]/20 z-10">
        <div className="absolute -top-16 -right-16 w-80 h-80 bg-[#824199]/20 rounded-full blur-[80px] pointer-events-none" />
        <div className="absolute -bottom-20 -left-20 w-64 h-64 bg-[#f9d443]/10 rounded-full blur-[60px] pointer-events-none" />
        
        <div className="relative z-10 flex flex-col items-center gap-10 text-center">
          <h2 className="font-['Newsreader'] font-normal text-white text-[56px] md:text-[64px] leading-[1.1] tracking-tight max-w-3xl">
            Ready to join the <br /> <span className="italic text-[#f9d443]">future</span> of Gold trading?
          </h2>
          <p className="font-light text-white/90 text-lg md:text-xl max-w-lg leading-relaxed">
            ปลดล็อกศักยภาพการเทรดด้วย AI Agent ที่พร้อมวิเคราะห์ตลาด 
            และแนะนำจุดเข้า-ออกที่แม่นยำให้คุณตัดสินใจทำกำไรได้ทันที
          </p>
          <div className="pt-4">
            <button onClick={handleGoToOverview} className="bg-white text-gray-900 px-10 py-4 rounded-full text-base font-bold shadow-xl hover:bg-gray-100 hover:scale-105 transition-all active:scale-95 flex items-center gap-2">
              Get Signal Alerts <ArrowUpRight size={18} className="text-gray-400"/>
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-4xl text-center mt-10 px-4 relative z-10">
        <p className="text-[#11182780] text-sm leading-relaxed font-normal">
          Disclaimer: การลงทุนมีความเสี่ยง ข้อมูลและสัญญาณเป็นเพียงเครื่องมือช่วยตัดสินใจทางคณิตศาสตร์ ไม่มีการันตีผลกำไร <br className="hidden md:block" /> ผลการดำเนินงานในอดีตมิได้เป็นสิ่งยืนยันถึงผลการดำเนินงานในอนาคต
        </p>
      </div>
    </section>
  );
};
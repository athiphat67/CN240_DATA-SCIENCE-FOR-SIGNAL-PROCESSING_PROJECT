import React from 'react';
import { motion } from 'framer-motion';
import { Network, BrainCircuit, ShieldCheck, BellRing } from 'lucide-react';

const steps = [
  { icon: Network, bgColor: "bg-[#f5e6fa]", step: "STEP 1", title: "Data Ingestion", description: "ดึงราคาทองคำ XAU/USD, อินดิเคเตอร์ทางเทคนิค และประเมิน Sentiment ข่าวเศรษฐกิจโลกแบบเรียลไทม์" },
  { icon: BrainCircuit, bgColor: "bg-[#fef9e7]", step: "STEP 2", title: "AI Brain & ReAct Loop", description: "สมองกล AI วิเคราะห์สถานการณ์ และเลือกใช้เครื่องมือซ้ำแล้วซ้ำเล่า จนกว่าจะมั่นใจมากที่สุด ก่อนตัดสินใจ" },
  { icon: ShieldCheck, bgColor: "bg-[#f5e6fa]", step: "STEP 3", title: "Risk Gate", description: "ตรวจสอบเวลาเปิด-ปิดตลาด, ล็อกเพดานขาดทุนรายวัน และคำนวณแนะนำ SL/TP ด้วยค่าความผันผวนจริง" },
  { icon: BellRing, bgColor: "bg-[#fef9e7]", step: "STEP 4", title: "Smart Alerts", description: "ส่งสัญญาณเตือนเข้ามือถือคุณทันที พร้อมอธิบายลอจิกและเหตุผลเบื้องหลัง อย่างโปร่งใส" },
];

// ตั้งค่า Animation สำหรับ Container หลัก
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.3 } // หน่วงเวลาให้โผล่มาทีละ 0.3 วิ
  }
};

// ตั้งค่า Animation สำหรับแต่ละ Step
const itemVariants = {
  hidden: { opacity: 0, y: 30 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" } }
};

export const HowItWorksStepsSection = () => {
  return (
    <section id="how-it-works" className="relative w-full py-24 px-8 flex flex-col items-center bg-transparent scroll-mt-24 z-0 overflow-x-clip overflow-y-visible">
      
      {/* Background Glow */}
      <motion.div animate={{ scale: [1, 1.05, 1], opacity: [0.03, 0.05, 0.03] }} transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }} className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[800px] h-[500px] bg-[#824199] rounded-full blur-[120px] pointer-events-none -z-10" />

      <div className="max-w-screen-xl w-full flex flex-col items-center gap-20 relative z-10">
        
        {/* Header Section */}
        <motion.div 
          initial={{ opacity: 0, y: -20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.5 }}
          transition={{ duration: 0.6 }}
          className="flex flex-col items-center gap-4 text-center"
        >
          <h2 className="font-['Newsreader'] font-normal text-gray-900 text-5xl tracking-tight leading-tight">
            How it <span className="text-[#824199] italic">Works</span>
          </h2>
          <p className="text-[#11182780] text-base font-normal max-w-lg">
            Our multi-layered AI architecture ensures precision and speed.
          </p>
        </motion.div>

        {/* Steps Grid */}
        <motion.div 
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true, amount: 0.2 }} // ทำงานเมื่อเลื่อนลงมาเห็น 20% ของกล่อง
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 w-full gap-y-12 lg:gap-y-0 relative"
        >
          {steps.map((item, index) => (
            <motion.div 
              key={index} 
              variants={itemVariants}
              whileHover={{ y: -5 }} // ยกตัวขึ้นเล็กน้อยตอน Hover
              className="group flex flex-col items-center text-center px-6 relative cursor-pointer"
            >
              
              {/* เส้นเชื่อม (Dashed Line) พร้อมจุดแสงวิ่ง */}
              {index < steps.length - 1 && (
                <div className="hidden lg:block absolute top-[32px] left-[50%] w-full h-[2px] border-t-2 border-dashed border-[#824199]/20 -z-10">
                  {/* จุดแสงวิ่งแสดงถึง Data Flow */}
                  <motion.div
                    animate={{ left: ["0%", "100%"], opacity: [0, 1, 1, 0] }}
                    transition={{ 
                      duration: 7, 
                      repeat: Infinity, 
                      ease: "linear", 
                      delay: index * 0.1 // หน่วงเวลาให้วิ่งต่อๆ กัน
                    }}
                    className="absolute -top-[5px] w-2 h-2 rounded-full bg-[#824199] shadow-[0_0_10px_#824199]"
                  />
                </div>
              )}

              {/* Icon Box */}
              <div className={`w-16 h-16 ${item.bgColor} rounded-2xl flex items-center justify-center shadow-sm mb-6 transition-all duration-300 group-hover:scale-110 group-hover:shadow-[0_10px_20px_rgba(130,65,153,0.15)]`}>
                <item.icon size={24} className="text-[#824199] transition-transform duration-300 group-hover:rotate-6" strokeWidth={2} />
              </div>

              {/* Text Content */}
              <span className="text-[#824199]/50 group-hover:text-[#824199] text-[10px] font-bold tracking-[0.15em] mb-3 transition-colors duration-300">
                {item.step}
              </span>
              <h3 className="text-gray-900 text-lg font-semibold mb-3 group-hover:text-[#824199] transition-colors duration-300">
                {item.title}
              </h3>
              <p className="text-[#11182799] text-xs leading-[1.8] max-w-[220px]">
                {item.description}
              </p>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}
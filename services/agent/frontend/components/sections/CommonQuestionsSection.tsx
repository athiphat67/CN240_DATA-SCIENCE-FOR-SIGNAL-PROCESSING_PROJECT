import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown } from "lucide-react";

const faqData = [
  { 
    id: 1, 
    question: "จะได้รับสัญญาณการเทรดผ่านช่องทางไหน?", 
    answer: "เมื่อคุณเริ่มใช้งาน ระบบจะส่งสัญญาณวิเคราะห์แบบ Real-time ตรงถึงมือคุณผ่านทาง Telegram และ Discord Server ส่วนตัวของเรา ทำให้คุณไม่พลาดทุกจังหวะสำคัญในการเข้าซื้อขายทองคำแท่ง 96.5%" 
  },
  { 
    id: 2, 
    question: "หากไม่เคยมีพื้นฐานการเทรดมาก่อน จะใช้งานได้ไหม?", 
    answer: "ใช้งานได้แน่นอนครับ ระบบถูกออกแบบมาให้เข้าใจง่ายและใช้งานได้จริง แม้ไม่มีพื้นฐาน เพราะเราทำหน้าที่เป็น 'ผู้ช่วยวิเคราะห์' ที่คัดกรองข้อมูลตลาดมาให้แล้ว คุณไม่จำเป็นต้องอ่านกราฟหรือวิเคราะห์ตลาดเอง เพียงแค่รอสัญญาณแจ้งเตือนและตัดสินใจตามคำแนะนำของเราได้ทันที" 
  },
  { 
    id: 3, 
    question: "มีระบบทดลองใช้งานก่อนตัดสินใจไหม?", 
    answer: "มีครับ! เราอยากให้คุณมั่นใจในความแม่นยำและระบบของเราก่อน เราจึงมอบสิทธิ์ทดลองใช้งาน (Free Trial) ให้คุณได้ทดสอบระบบจริงฟรี 3 ครั้ง เพื่อให้คุณเห็นภาพชัดเจนว่า AI ช่วยการตัดสินใจซื้อทองของคุณได้แม่นยำแค่ไหน" 
  },
  { 
    id: 4, 
    question: "AI วิเคราะห์ทองคำประเภทไหนเป็นหลัก?", 
    answer: "AI Agent ของเราถูกพัฒนาขึ้นมาเพื่อวิเคราะห์จังหวะการเข้าซื้อทองคำแท่ง 96.5% โดยเฉพาะ (อ้างอิงราคามาตรฐานฮั่วเซ่งเฮง) เพื่อให้สอดคล้องกับพฤติกรรมราคาทองคำในตลาดไทยมากที่สุดครับ" 
  },
  { 
    id: 5, 
    question: "ทำไมต้องใช้ AI ของ NAKKHUTTONG?", 
    answer: "เพราะการลงทุนในตลาดทองคำต้องอาศัยจังหวะเวลาที่แม่นยำ AI ของเราช่วยตัดอารมณ์ความรู้สึกและความลังเลใจออกไป โดยเน้นการวิเคราะห์ข้อมูลเชิงลึกตลอด 24 ชั่วโมง ให้คุณได้คำตอบที่ชัดเจนที่สุดในการวางแผนทำกำไรในทุกรอบการเทรด" 
  },
];

export const CommonQuestionsSection = () => {
  const [openId, setOpenId] = useState<number | null>(null);

  const handleToggle = (id: number) => setOpenId((prev) => (prev === id ? null : id));

  return (
    <section id="faq" className="relative flex flex-col items-center w-full py-24 px-8 bg-transparent scroll-mt-24 z-0 overflow-x-clip overflow-y-visible">
      
      <motion.div animate={{ scale: [1, 1.05, 1], opacity: [0.03, 0.05, 0.03] }} transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }} className="absolute bottom-10 right-[15%] w-[500px] h-[500px] bg-[#824199] rounded-full blur-[100px] pointer-events-none -z-10" />

      <div className="max-w-screen-md w-full flex flex-col gap-12 relative z-10">
        <div className="text-center">
          <h2 className="font-['Newsreader'] font-normal text-gray-900 text-4xl tracking-tight leading-tight">
            Common Questions
          </h2>
        </div>

        <div className="flex flex-col gap-4">
          {faqData.map((item) => (
            <div key={item.id} className="group flex flex-col bg-white/80 backdrop-blur-xl border border-gray-100/80 rounded-2xl overflow-hidden transition-all duration-300 hover:border-[#824199]/20 shadow-[0_4px_20px_rgba(0,0,0,0.02)]">
              <button type="button" className="flex items-center justify-between p-6 text-left w-full transition-colors group-hover:bg-[#824199]/05" onClick={() => handleToggle(item.id)}>
                <span className="text-gray-900 font-semibold text-base leading-6">{item.question}</span>
                <motion.div animate={{ rotate: openId === item.id ? 180 : 0 }} transition={{ duration: 0.3, ease: "easeInOut" }} className="text-[#824199]">
                  <ChevronDown size={20} />
                </motion.div>
              </button>

              <AnimatePresence>
                {openId === item.id && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.3, ease: "easeInOut" }}>
                    <div className="px-6 pb-6 pt-0 text-[#11182780] text-sm leading-relaxed">{item.answer}</div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
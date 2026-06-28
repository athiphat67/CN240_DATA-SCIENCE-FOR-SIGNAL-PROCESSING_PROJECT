import { motion } from 'framer-motion';
import { TrendingUp, Activity, BarChart2, ArrowUpRight, Sparkles, PlayCircle, ShieldCheck } from 'lucide-react';
import logoImg from '../../images/logo.png';

const fadeInUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.8, ease: [0.16, 1, 0.3, 1] } 
};

const staggerContainer = {
  animate: { transition: { staggerChildren: 0.15 } }
};

const floatingAnimation = {
  animate: {
    y: [0, -6, 0],
    transition: { duration: 6, repeat: Infinity, ease: "easeInOut" }
  }
};

const ActiveSignalWidget = () => (
  <motion.div variants={floatingAnimation} className="flex flex-col gap-4 w-full md:w-[300px]">
    {/* Box 1: Signal */}
    <div className="group bg-white hover:bg-[#824199] rounded-[28px] p-6 shadow-[0px_8px_24px_rgba(0,0,0,0.03)] hover:shadow-[0_20px_40px_rgba(130,65,153,0.25)] border border-gray-100 hover:border-transparent transition-all duration-500 cursor-pointer">
      <div className="flex items-center justify-between mb-5">
        <span className="text-sm font-bold text-gray-800 group-hover:text-white transition-colors duration-500">Active Signal</span>
        <div className="relative">
          <Activity size={20} className="text-[#824199] group-hover:text-[#f9d443] transition-colors duration-500" strokeWidth={2.5} />
          <span className="absolute -top-1 -right-1 flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500 group-hover:bg-[#f9d443] transition-colors duration-500"></span>
          </span>
        </div>
      </div>
      <div className="flex gap-2">
        <span className="bg-[#824199] group-hover:bg-[#f9d443] text-white group-hover:text-gray-900 text-[11px] font-bold px-5 py-2.5 rounded-full shadow-md flex-1 text-center transition-colors duration-500">BUY</span>
        <span className="bg-gray-50 group-hover:bg-white/20 text-gray-500 group-hover:text-white/90 text-[11px] font-bold px-5 py-2.5 rounded-full flex-1 text-center transition-colors duration-500">HOLD</span>
         <span className="bg-gray-50 group-hover:bg-white/20 text-gray-500 group-hover:text-white/90 text-[11px] font-bold px-5 py-2.5 rounded-full flex-1 text-center transition-colors duration-500">SELL</span>
      </div>
    </div>

    {/* Box 2: Confidence */}
    <div className="group bg-white hover:bg-[#824199] rounded-[28px] p-6 shadow-[0px_8px_24px_rgba(0,0,0,0.03)] hover:shadow-[0_20px_40px_rgba(130,65,153,0.25)] border border-gray-100 hover:border-transparent transition-all duration-500 cursor-pointer">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-bold text-gray-800 group-hover:text-white transition-colors duration-500">AI Confidence</span>
      </div>
      <div className="flex items-center gap-4">
        <div className="relative flex items-center justify-center w-12 h-12">
          <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
            <path className="text-gray-100 group-hover:text-white/20 transition-colors duration-500" strokeWidth="3" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
            <path className="text-[#824199] group-hover:text-[#f9d443] transition-colors duration-500" strokeDasharray="85, 100" strokeWidth="3" strokeLinecap="round" stroke="currentColor" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
          </svg>
          <span className="absolute text-[11px] font-bold text-gray-800 group-hover:text-white transition-colors duration-500">85%</span>
        </div>
        <div className="flex flex-col">
          <span className="text-xs font-bold text-gray-800 group-hover:text-white transition-colors duration-500">Strong Buy Signal</span>
          <p className="text-[10px] text-gray-400 group-hover:text-white/70 mt-0.5 transition-colors duration-500">USD weakness detected.</p>
        </div>
      </div>
    </div>
  </motion.div>
);

const GoldPriceWidget = () => (
  <motion.div variants={floatingAnimation} transition={{ delay: 0.2 }} className="group bg-white hover:bg-[#824199] rounded-[32px] p-8 shadow-[0px_12px_30px_rgba(0,0,0,0.04)] hover:shadow-[0_30px_60px_rgba(130,65,153,0.3)] border border-gray-100 hover:border-transparent w-full md:w-[340px] h-full flex flex-col justify-between relative overflow-hidden transition-all duration-500 cursor-pointer mt-4 md:mt-0">
    {/* Decorative blur inside card that appears on hover */}
    <div className="absolute -top-10 -right-10 w-40 h-40 bg-[#f9d443] rounded-full blur-[60px] opacity-0 group-hover:opacity-20 transition-opacity duration-700 pointer-events-none" />
    
    <div>
      <div className="flex items-center justify-between mb-6 relative z-10">
        <span className="text-base font-extrabold text-gray-900 group-hover:text-white transition-colors duration-500">Thai Gold 96.5%</span>
        <div className="p-2.5 bg-gray-50 group-hover:bg-white/10 rounded-xl text-[#824199] group-hover:text-[#f9d443] transition-colors duration-500">
          <TrendingUp size={20} strokeWidth={2.5} />
        </div>
      </div>
      
      <div className="bg-gray-50 group-hover:bg-white/10 rounded-2xl p-4 mb-10 flex items-center justify-between transition-colors duration-500 relative z-10">
        <span className="text-xs font-medium text-gray-500 group-hover:text-white/80 transition-colors duration-500">Oracle Sync</span>
        <div className="flex items-center gap-2 bg-white group-hover:bg-white/20 px-3 py-1.5 rounded-full shadow-sm transition-colors duration-500">
          <div className="w-1.5 h-1.5 bg-green-500 group-hover:bg-[#f9d443] rounded-full animate-pulse transition-colors duration-500" />
          <span className="text-[10px] font-mono text-gray-600 group-hover:text-white font-bold transition-colors duration-500">Live Data</span>
        </div>
      </div>
    </div>

    <div className="relative z-10">
      <span className="text-[40px] font-black text-gray-900 group-hover:text-white tracking-tight leading-none transition-colors duration-500">41,200 ฿</span>
      <div className="flex items-center justify-between mt-3">
        <span className="text-sm font-semibold text-gray-400 group-hover:text-white/70 transition-colors duration-500">Buy: 41,100 ฿</span>
        <div className="flex items-center gap-1 bg-green-50 group-hover:bg-[#f9d443]/20 px-2.5 py-1 rounded-lg text-green-600 group-hover:text-[#f9d443] transition-colors duration-500">
          <ArrowUpRight size={14} strokeWidth={3} />
          <span className="text-xs font-bold">+50 ฿</span>
        </div>
      </div>
    </div>
  </motion.div>
);

const SignalAccuracyWidget = () => (
  <motion.div variants={floatingAnimation} transition={{ delay: 0.4 }} className="group bg-white hover:bg-[#824199] rounded-[32px] p-8 shadow-[0px_12px_30px_rgba(0,0,0,0.04)] hover:shadow-[0_20px_40px_rgba(130,65,153,0.3)] border border-gray-100 hover:border-transparent w-full md:w-[300px] transition-all duration-500 cursor-pointer">
    <div className="flex items-center justify-between mb-6">
      <span className="text-sm font-bold text-gray-800 group-hover:text-white transition-colors duration-500">Signal Accuracy</span>
      <BarChart2 size={20} className="text-[#824199] group-hover:text-[#f9d443] transition-colors duration-500" />
    </div>
    
    <div className="mb-8">
      <div className="flex items-end gap-2">
        <h3 className="text-4xl font-black text-[#824199] group-hover:text-white transition-colors duration-500">84.2%</h3>
      </div>
      <p className="text-[11px] font-bold text-gray-400 group-hover:text-white/70 uppercase tracking-wider mt-2 transition-colors duration-500">Win Rate (Last 30 Days)</p>
    </div>

    {/* Modern Progress Bars */}
    <div className="space-y-3">
      {[
        { label: 'Buy Signals', val: 88, baseColor: 'bg-[#824199]', hoverColor: 'group-hover:bg-[#f9d443]' },
        { label: 'Sell Signals', val: 76, baseColor: 'bg-gray-300', hoverColor: 'group-hover:bg-white/60' }
      ].map((item, i) => (
        <div key={i} className="space-y-1.5">
          <div className="flex justify-between text-[10px] font-bold text-gray-500 group-hover:text-white/90 transition-colors duration-500">
            <span>{item.label}</span>
            <span>{item.val}%</span>
          </div>
          <div className="w-full bg-gray-100 group-hover:bg-white/20 rounded-full h-1.5 overflow-hidden transition-colors duration-500">
            <motion.div 
              initial={{ width: 0 }}
              animate={{ width: `${item.val}%` }}
              transition={{ duration: 1.5, delay: 0.5 }}
              className={`h-full rounded-full ${item.baseColor} ${item.hoverColor} transition-colors duration-500`} 
            />
          </div>
        </div>
      ))}
    </div>
  </motion.div>
);

export const HeroSection = () => {
  const handleGoToOverview = () => window.location.href = '/overview';
  const handleGoToAIAnalysis = () => window.location.href = '/agent-analysis';


  return (
    <motion.section 
      id="home" 
      initial="initial" 
      animate="animate" 
      variants={staggerContainer} 
      /* ใช้ bg-transparent เพื่อให้สีจาก bg-premium-gradient ในไฟล์หลักทะลุขึ้นมา */
      className="relative w-full min-h-screen flex flex-col items-center pt-8 pb-24 px-6 md:px-8 bg-transparent z-0 overflow-visible"
    >

      {/* Logo */}
      <motion.div variants={fadeInUp} className="z-20 mb-6">
        <img 
          src={logoImg} 
          alt="NAKKHUTTONG Logo" 
          className="h-20 md:h-24 w-auto mx-auto mix-blend-multiply object-contain" 
        />
      </motion.div>

      {/* Headline - ปรับฟอนต์ให้ดู Luxury นิ่งๆ ไม่ไล่สีฉูดฉาด */}
      <motion.div variants={fadeInUp} className="z-20 text-center mb-6 max-w-4xl">
        <h1 className="font-['Newsreader'] font-medium text-gray-900 text-5xl md:text-[76px] leading-[1.05] tracking-tight">
          The Next Era of <br className="hidden md:block" />
          <span className="font-['Newsreader'] italic font-semibold text-[#824199]">Thai gold</span> Intelligence
        </h1>
      </motion.div>

      {/* Subtitle */}
      <motion.p variants={fadeInUp} className="z-20 text-center text-gray-500 text-sm md:text-base leading-relaxed mb-10 max-w-2xl mx-auto font-medium">
        รับสัญญาณเทรดทองคำแท้ 96.5% สุดแม่นยำ ด้วย AI Agent ที่วิเคราะห์ตลาดแบบ Real-time <br className="hidden md:block" /> แจ้งเตือนจุด Buy, Sell, Hold ให้คุณตัดสินใจทำกำไรได้ทันที
      </motion.p>

      {/* CTA Buttons */}
      <motion.div variants={fadeInUp} className="z-20 mb-12 flex flex-col sm:flex-row items-center gap-4">
        
        {/* Primary Button (ปุ่มหลักสีม่วง 3D + Glow) */}
        <button 
          onClick={handleGoToOverview} 
          className="group relative flex items-center gap-2 bg-gradient-to-b from-[#9d53b8] to-[#824199] text-white px-8 py-4 rounded-full text-sm font-bold shadow-[0_8px_24px_rgba(130,65,153,0.35)] hover:shadow-[0_12px_32px_rgba(130,65,153,0.5)] hover:-translate-y-1 transition-all duration-300 w-full sm:w-auto justify-center border border-white/10"
        >
          {/* เงาสะท้อนแสงด้านบนปุ่มให้ดูนูน (Inner Glow) */}
          <div className="absolute inset-0 rounded-full border-t border-white/20 pointer-events-none" />
          
          <span className="relative z-10 flex items-center gap-2">
            Get Signal Alerts 
            <ArrowUpRight size={18} className="text-[#f9d443] group-hover:translate-x-1 group-hover:-translate-y-1 transition-transform" />
          </span>
        </button>

        {/* Secondary Button (ปุ่มรองสีม่วงใสๆ ขอบบาง) */}
        <button 
          onClick={handleGoToAIAnalysis} 
          className="group flex items-center gap-2 bg-[#824199]/[0.03] text-[#824199] px-8 py-4 rounded-full text-sm font-bold border border-[#824199]/20 hover:bg-[#824199]/10 hover:border-[#824199]/40 hover:-translate-y-1 transition-all duration-300 w-full sm:w-auto justify-center"
        >
          <PlayCircle size={18} className="text-[#824199] group-hover:scale-110 transition-transform duration-300" />
          View Live Performance
        </button>

      </motion.div>

      {/* Trust Signal */}
      <motion.div variants={fadeInUp} className="z-20 mb-16 flex items-center gap-2 text-xs font-semibold text-gray-400">
        <ShieldCheck size={16} className="text-[#824199]/60" />
        <span>วิเคราะห์ข้อมูลสดจากตลาดทองคำไทยตลอด 24 ชม.</span>
      </motion.div>

      {/* Widgets Bento Box */}
      <motion.div variants={staggerContainer} className="z-20 flex flex-col md:flex-row items-stretch gap-6 flex-wrap justify-center w-full max-w-6xl px-4">
        <ActiveSignalWidget />
        <GoldPriceWidget />
        <SignalAccuracyWidget />
      </motion.div>
    </motion.section>
  );
};
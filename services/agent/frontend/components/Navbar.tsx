import React, { useState, useEffect, useRef } from "react"; // ✨ อย่าลืม import useRef
import { motion, AnimatePresence } from "framer-motion";
import { Menu, X } from "lucide-react";

export const Navbar = () => {
  const [activeSection, setActiveSection] = useState("home");
  const [isOpen, setIsOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);
  
  // ✨ เพิ่มตัวแปร Ref เพื่อล็อกไม่ให้ Scroll เช็คค่ามั่วตอนกำลังกดปุ่ม
  const isClickScrolling = useRef(false);

  const scrollToSection = (e: React.MouseEvent, id: string) => {
    e.preventDefault();
    setIsOpen(false);
    
    // บังคับเปลี่ยนสีปุ่มทันทีที่กด
    const sectionId = id.replace("#", "");
    setActiveSection(sectionId);

    // ✨ เปิดล็อก! แจ้งบอกว่า "กำลังเลื่อนอัตโนมัติอยู่นะ ห้าม handleScroll ทำงาน"
    isClickScrolling.current = true;

    const lenis = (window as any).lenis;
    if (lenis) {
      lenis.scrollTo(id, {
        offset: -100,
        duration: 2.5,
        easing: (t: number) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      });
      
      // ✨ ปลดล็อก! หลังจาก Lenis เลื่อนเสร็จ (2.5 วินาที + เผื่อเวลาเล็กน้อย)
      setTimeout(() => {
        isClickScrolling.current = false;
      }, 2600); 

    } else {
      const element = document.querySelector(id);
      element?.scrollIntoView({ behavior: "smooth" });
      setTimeout(() => { isClickScrolling.current = false; }, 1000);
    }
  };

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20);

      // ✨ ถ้ากำลังเลื่อนเพราะกดปุ่ม ให้หยุดทำงานฟังก์ชันนี้ไปเลย! (แก้ปัญหาไฟกระพริบไปมา)
      if (isClickScrolling.current) return;

      const sections = ["home", "features", "how-it-works", "performance", "faq"];
      
      // เช็คว่าสุดหน้าจอจริงๆ หรือยัง (เผื่อมือถือ) 
      // ใช้ Math.ceil ป้องกันจุดทศนิยมทำให้สมการผิดเพี้ยน
      const isBottom = Math.ceil(window.innerHeight + window.scrollY) >= document.documentElement.scrollHeight - 50;
      
      if (isBottom) {
        setActiveSection("faq");
        return;
      }

      // ✨ เปลี่ยนจาก +120 เป็นใช้อัตราส่วนหน้าจอ (1 ใน 3 ของจอ) 
      // เพื่อให้จับ Section ที่สั้นๆ หรืออยู่ล่างสุดได้แม่นยำขึ้น
      const triggerPoint = window.scrollY + (window.innerHeight / 3);

      sections.forEach((section) => {
        const element = document.getElementById(section);
        if (element) {
          const offsetTop = element.offsetTop;
          const height = element.offsetHeight;

          if (triggerPoint >= offsetTop && triggerPoint < offsetTop + height) {
            setActiveSection(section);
          }
        }
      });
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const menuItems = [
    { name: "Home", href: "#home", id: "home" },
    { name: "Features", href: "#features", id: "features" },
    { name: "How it Works", href: "#how-it-works", id: "how-it-works" },
    { name: "Performance", href: "#performance", id: "performance" },
    { name: "FAQ", href: "#faq", id: "faq" },
  ];

  return (
    <>
      {/* โค้ดส่วน UI ของ Navbar ทั้งหมดเหมือนเดิมครับ ไม่ต้องแก้ */}
      <nav
        className={`fixed top-4 left-1/2 -translate-x-1/2 z-[100] w-[92%] max-w-6xl flex items-center justify-between px-6 py-3 rounded-full transition-all duration-500 ${
          isScrolled
            ? "bg-white/90 backdrop-blur-lg border border-gray-200/60 shadow-[0_8px_30px_rgba(0,0,0,0.04)]"
            : "bg-white border border-gray-100 shadow-[0_4px_20px_rgba(0,0,0,0.02)]"
        }`}
      >
        {/* ฝั่งซ้าย: Logo */}
        <div
          className="flex items-center gap-3 cursor-pointer group z-[101]"
          onClick={(e) => scrollToSection(e, "#home")}
        >
          <div className="w-8 h-8 md:w-9 md:h-9 border-[1.5px] border-[#824199] rounded-full flex items-center justify-center bg-white transition-transform duration-300 group-hover:scale-105 shadow-sm">
            <div className="w-4 h-4 md:w-4 md:h-4 bg-white rounded-full flex items-center justify-center">
              <div className="w-2 md:w-2 h-2 md:h-2 bg-yellow-400 rounded-full shadow-[0_0_8px_rgba(250,204,21,0.6)]" />
            </div>
          </div>
          <span className="font-bold text-base md:text-lg tracking-tight text-gray-900 group-hover:text-[#824199] transition-colors">
            NAKKHUTTHONG
          </span>
        </div>

        {/* ฝั่งกลาง: Menu Links (Desktop) */}
        <div className="hidden md:flex items-center gap-1 text-[14px] font-medium text-gray-500 bg-gray-50/50 p-1 rounded-full border border-gray-100/50 backdrop-blur-sm">
          {menuItems.map((item) => {
            const isActive = activeSection === item.id;
            return (
              <a
                key={item.id}
                href={item.href}
                onClick={(e) => scrollToSection(e, item.href)}
                className={`relative px-5 py-2 rounded-full transition-all duration-300 ${
                  isActive ? "text-white" : "hover:text-[#824199]"
                }`}
              >
                <span className="relative z-10 transition-colors duration-300">
                  {item.name}
                </span>

                {isActive && (
                  <motion.div
                    layoutId="activeTab"
                    className="absolute inset-0 bg-gradient-to-r from-[#824199] to-[#6d3580] shadow-[0_4px_15px_rgba(130,65,153,0.3)] rounded-full"
                    transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
                  />
                )}

                {!isActive && (
                  <div className="absolute inset-0 bg-black/0 hover:bg-[#824199]/5 rounded-full transition-colors duration-300" />
                )}
              </a>
            );
          })}
        </div>

        {/* ฝั่งขวา: ปุ่ม Start Now & Hamburger */}
        <div className="flex items-center gap-3">
          <button
            onClick={() => (window.location.href = "/overview")}
            className="hidden sm:block bg-[#824199] text-white px-6 py-2.5 rounded-full text-sm font-semibold shadow-[0_8px_20px_-6px_rgba(130,65,153,0.5)] hover:shadow-[0_10px_25px_-6px_rgba(130,65,153,0.6)] hover:-translate-y-0.5 hover:bg-[#6d3580] transition-all active:scale-95 border border-[#824199]/20"
          >
            Start now
          </button>

          <button
            className="p-2 md:hidden text-gray-600 hover:text-[#824199] hover:bg-gray-50 rounded-full transition-colors"
            onClick={() => setIsOpen(!isOpen)}
          >
            {isOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </nav>

      {/* Mobile Menu Overlay */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="fixed top-20 left-[4%] right-[4%] z-[90] bg-white/95 backdrop-blur-xl border border-gray-100 rounded-3xl shadow-[0_20px_40px_rgba(0,0,0,0.08)] p-6 flex flex-col gap-2 md:hidden"
          >
            {menuItems.map((item) => (
              <a
                key={item.id}
                href={item.href}
                onClick={(e) => scrollToSection(e, item.href)}
                className={`text-base font-semibold px-4 py-3.5 rounded-2xl transition-all ${
                  activeSection === item.id
                    ? "bg-[#824199]/10 text-[#824199]"
                    : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                }`}
              >
                {item.name}
              </a>
            ))}
            <button
              onClick={() => (window.location.href = "/overview")}
              className="w-full bg-[#824199] text-white py-4 rounded-2xl font-bold mt-4 shadow-[0_8px_20px_-6px_rgba(130,65,153,0.5)] active:scale-95 transition-transform"
            >
              Start Now
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};
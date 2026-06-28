# 📖 About Frontend — NAKKHUTTHONG Gold Trading Agent

เอกสารนี้อธิบายโครงสร้าง สถาปัตยกรรม และแนวทางการพัฒนา Frontend ของโปรเจกต์ CN240  
เขียนไว้สำหรับ Developer ที่จะเข้ามาทำงานต่อหรือ contribute ในโปรเจกต์นี้

---

## 🗂️ โครงสร้างโฟลเดอร์

```

```

---

## 🛠️ Tech Stack

| เทคโนโลยี | เวอร์ชัน | หน้าที่ |
|---|---|---|
| **React** | 19.x | UI Framework |
| **TypeScript** | 6.x | Type Safety |
| **Vite** | 8.x | Build Tool / Dev Server |
| **Tailwind CSS** | 4.x | Utility-first Styling |
| **Framer Motion** | 12.x | Animations & Transitions |
| **Lenis** | 1.x | Smooth Scroll |
| **Lucide React** | 1.x | Icon Library |

---

## 🚀 การเริ่มต้น

### ติดตั้ง dependencies

```bash
npm install
npm install recharts
npm install react-apexcharts apexcharts
```

### รัน Dev Server
  Terminal 1 รัน
python main.py

  terminal 2
```bash
npm run dev

  terminal 3
# cd เข้า  cd CN240_DATA-SCIENCE-FOR-SIGNAL-PROCESSING_PROJECT/Src/frontend/api 
python -m uvicorn main:app --reload

```

Dev Server จะเปิดที่ `http://localhost:5173` (Vite default)

### Build สำหรับ Production

```bash
npm run build
```

Output จะอยู่ในโฟลเดอร์ `dist/`

### Preview Production Build

```bash
npm run preview
```

---

## 🏗️ สถาปัตยกรรม

### Entry Point (`pages/index.tsx`)

ไฟล์หลักของแอปคือ `pages/index.tsx` ซึ่งทำหน้าที่:

1. **Smooth Scroll (Lenis)** — สร้าง `Lenis` instance ใน `useEffect` และแขวน `requestAnimationFrame` loop ไว้ตลอด lifecycle ของ app พร้อม expose ไว้ใน `window.lenis` เพื่อให้ component อื่น (เช่น Navbar) เรียกใช้ได้
2. **Layout** — จัดเรียง Section components ตามลำดับ vertical
3. **Global Background** — ใช้สี `#FCFBF7` เป็น background หลักของทั้งหน้า

```tsx
// Lenis เปิดใช้งานตรงนี้ และ expose ไว้ที่ window.lenis
const lenis = new Lenis({ duration: 2.5, lerp: 0.05, smoothWheel: true });
(window as any).lenis = lenis;
```

### Navbar (`components/ui/Navbar.tsx`)

- **Fixed + Floating** — ใช้ `fixed top-4` และ `rounded-full` เพื่อทำ floating pill style
- **Active Section Detection** — ใช้ `window.scrollY` + `offsetTop` ของแต่ละ `section[id]` เพื่อ highlight เมนูที่ active
- **Smooth Scroll** — เรียก `window.lenis.scrollTo(id)` พร้อม `offset: -100` เพื่อไม่ให้ Navbar บัง heading
- **Framer Motion** — ใช้ `layoutId="activeTab"` เพื่อทำ animated active indicator แบบ spring

Section IDs ที่ Navbar track:

```
home | features | how-it-works | performance | faq
```

---

## 📦 Section Components

แต่ละ Section อยู่ใน `components/sections/` และรับ `id` ตรงกับที่ Navbar ใช้ track

| Component | Section ID | คำอธิบาย |
|---|---|---|
| `HeroSection` | `#home` | Hero หลัก + Widget Cards (signal, price, accuracy) |
| `GoldPortfolioInsightsSection` | `#features` | Feature cards 4 ใบ (Advanced Reasoning, Risk Management, etc.) |
| `HowItWorksStepsSection` | `#how-it-works` | 4-step process พร้อม connector line (desktop) |
| `TransparentRationaleSection` | `#performance` | Carousel แสดง AI reasoning ของสัญญาณ BUY/HOLD/SELL |
| `CommonQuestionsSection` | `#faq` | Accordion FAQ |
| `GoldTradingCTASection` | — | CTA Banner + Disclaimer (ไม่มี scroll target) |

---

## 🎨 Design System

### สีหลัก

```css
--purple-primary:  #824199   /* Brand color หลัก */
--purple-dark:     #6d3580   /* Hover state */
--gold-accent:     #f9d443   /* Accent / highlight */
--bg-base:         #FCFBF7   /* Page background */
--text-primary:    #111827   /* Gray-900 เทียบเท่า */
--text-muted:      #11182780 /* 50% opacity */
```

### Typography

- **Headings** — `font-['Newsreader']` (serif) โหลดจาก Google Fonts, weight 200–800, รองรับ italic
- **Body / UI** — System font stack ของ Tailwind (Inter-like)
- **Italic accent** — ใช้ `<span className="italic text-[#824199]">` สำหรับคำ highlight ใน headline

### Spacing & Shape

- Section padding: `py-24 px-8`
- Card border-radius: `rounded-[32px]` หรือ `rounded-[40px]`
- Navbar: `rounded-full`
- Shadow: `shadow-[0_20px_50px_rgba(0,0,0,0.04)]` (subtle, premium feel)

### Glassmorphism

Cards ส่วนใหญ่ใช้ pattern:

```tsx
className="bg-white/60 backdrop-blur-xl border border-white/20 rounded-[32px]"
```

---

## ✨ Animation Guidelines

โปรเจกต์นี้ใช้ Framer Motion ในหลายจุด — ควรทำตามแนวทางต่อไปนี้เพื่อความ consistent:

**Fade-in + Slide up (มาตรฐาน):**

```tsx
const fadeInUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.8, ease: [0.16, 1, 0.3, 1] }
};
```

**Stagger children:**

```tsx
const staggerContainer = {
  animate: { transition: { staggerChildren: 0.1 } }
};
```

**Carousel (TransparentRationaleSection):**
- ใช้ `position` คำนวณจาก `index` เพื่อจัดการ 3-card 3D carousel
- Auto-play ทุก 3 วินาที หยุดเมื่อ `onMouseEnter`

---

## 🔧 Configuration Files

### `vite.config.ts`

```ts
// root คือ project root (มี index.html)
// input บังคับให้ใช้ index.html เป็น entry
root: './'
build: { rollupOptions: { input: 'index.html' } }
```

### `tailwind.config.cjs`

- Content scan: `./Src/**/*.{js,ts,jsx,tsx}` — **⚠️ หมายเหตุ:** path ใช้ `Src` (ตัวใหญ่) ตรวจสอบให้ตรงกับโครงสร้างจริง
- Custom font: `fontFamily.newsreader` เพิ่มไว้แล้ว

### `tailwind.css`

- `@import "tailwindcss"` — Tailwind v4 syntax
- Import Google Fonts (Newsreader) โดยตรง
- Base layer: reset `button`, `input`, `select`, `textarea`
- Global: `scroll-behavior: smooth` + `scroll-margin-top: 100px` ทุก section

### `tsconfig.json`

- `include`: `["Src", "pages", "components", "declarations.d.ts"]`
- `moduleResolution: "Bundler"` — เหมาะกับ Vite
- Strict mode เปิดอยู่

---

## ⚠️ สิ่งที่ต้องระวัง

1. **`window.lenis`** — Navbar อ่าน lenis จาก `window` โดยตรง หาก component โหลดก่อน `MainAppContainer` mount เสร็จ จะ fallback เป็น native `scrollIntoView`

2. **Tailwind content path** — `tailwind.config.cjs` ชี้ไปที่ `./Src/**` (ตัวใหญ่) แต่โฟลเดอร์จริงอาจเป็น `src` (ตัวเล็ก) — บน Linux case-sensitive อาจทำให้ purge class ไม่ถูกต้อง

3. **`lucide-react` เวอร์ชัน 1.x** — API อาจต่างจาก 0.x ที่พบในโปรเจกต์อื่น ตรวจสอบ import path ก่อนเพิ่ม icon ใหม่

4. **Image import** — ต้อง declare ใน `declarations.d.ts` (`declare module '*.png'`) ไม่เช่นนั้น TypeScript จะ error

5. **Framer Motion `AnimatePresence`** — ใช้ใน FAQ Accordion และ Carousel ควร wrap `exit` animation ทุกครั้งที่ conditional render

---

## 📝 การเพิ่ม Section ใหม่

1. สร้างไฟล์ใน `components/sections/NewSection.tsx`
2. กำหนด `id` ให้ `<section>` ตรงกับที่ต้องการ scroll to
3. Import และวางใน `pages/index.tsx` ตามลำดับที่ต้องการ
4. (Optional) เพิ่ม item ใน `menuItems` ของ `Navbar.tsx` ถ้าต้องการให้ปรากฏในเมนู

```tsx
// pages/index.tsx
import { NewSection } from "../components/sections/NewSection";

// ใน JSX:
<NewSection />
```

---

*Last updated: April 2026 — CN240 Data Science for Signal Processing*

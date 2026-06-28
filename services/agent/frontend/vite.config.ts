import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // ตรวจสอบว่า root คือโฟลเดอร์ปัจจุบันที่มี index.html
  root: './', 
  build: {
    outDir: 'dist',
    // บังคับให้ Vite รู้ว่าต้องเริ่มสแกนจาก index.html ตรงไหน
    rollupOptions: {
      input: 'index.html',
    },
  },
})
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./index.html",
    "./main.tsx",
    "./{components,pages,source,styles}/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        newsreader: ['Newsreader', 'serif'],
      },
    },
  },
  plugins: [],
}
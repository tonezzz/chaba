/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./public/**/*.html', './public/apps/nav.js'],
  safelist: ['group-hover:block', 'text-[10px]', 'min-w-[8rem]', 'z-[1100]'],
  theme: {
    extend: {
      colors: {
        bg: '#1a1a2e',
        card: '#16213e',
        accent: '#0a84ff'
      }
    }
  },
  plugins: []
};

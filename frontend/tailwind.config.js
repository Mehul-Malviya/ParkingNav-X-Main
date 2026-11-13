/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        vitap: {
          blue: '#003087',
          gold: '#FFD700',
        },
      },
    },
  },
  plugins: [],
}

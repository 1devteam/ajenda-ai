/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0C0E14',
        surface: '#13151E',
        'surface-2': '#1A1D2A',
        accent: '#6C63FF',
        'accent-dim': 'rgba(108,99,255,0.15)',
        success: '#22D3A0',
        warning: '#F59E0B',
        danger: '#EF4444',
        't1': '#F0F2F8',
        't2': '#8B93A8',
        't3': '#4A5168',
      },
      fontFamily: {
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '8px',
        lg: '12px',
      },
    },
  },
  plugins: [],
}

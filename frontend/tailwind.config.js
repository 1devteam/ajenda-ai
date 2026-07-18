/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        os: {
          bg: "#0b0d11",
          surface: "#12151b",
          "surface-elevated": "#1a1e27",
          border: "#2a3140",
        },
        brand: {
          DEFAULT: "#e8edf5",
          muted: "#94a3b8",
          accent: "#7dd3fc",
        },
        /* Keep for danger / blocking only — not general chrome */
        crimson: {
          DEFAULT: "#dc2626",
          bright: "#ef4444",
        },
        semantic: {
          success: "#22C55E",
          info: "#7DD3FC",
          warning: "#F59E0B",
        },
      },
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "sans-serif"],
        display: ['"Instrument Sans"', "system-ui", "sans-serif"],
      },
      borderRadius: {
        panel: "12px",
      },
      boxShadow: {
        lift: "0 8px 24px rgba(0, 0, 0, 0.35)",
        panel: "0 4px 16px rgba(0, 0, 0, 0.25)",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
    },
  },
  plugins: [require("@tailwindcss/container-queries")],
};

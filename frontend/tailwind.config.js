/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        os: {
          bg: "#111315",
          surface: "#181820",
          "surface-elevated": "#22222C",
          border: "#2E343B",
        },
        crimson: {
          DEFAULT: "#B3122B",
          bright: "#D91728",
        },
        semantic: {
          success: "#22C55E",
          info: "#38BDF8",
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
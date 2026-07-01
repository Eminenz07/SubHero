/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./templates/**/*.html",
    "./apps/**/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: "#006B3E",
          "primary-light": "#007A46",
          accent: "#00C46A",
          dark: "#0A1628",
        },
        surface: {
          page: "#F5F7FA",
          card: "#FFFFFF",
          border: "#E8ECF4",
        },
        text: {
          primary: "#0A1628",
          secondary: "#6B7A99",
          muted: "#A0AABF",
        },
        status: {
          danger: "#E53E3E",
          warning: "#F6AD1E",
          success: "#00C46A",
          "danger-bg": "#FEE2E2",
          "danger-text": "#DC2626",
          "warning-bg": "#FEF9C3",
          "warning-text": "#A16207",
          "success-bg": "#DCFCE7",
          "success-text": "#16A34A",
        }
      },
      fontFamily: {
        display: ["'Bricolage Grotesque'", "system-ui", "sans-serif"],
        body: ["'DM Sans'", "system-ui", "sans-serif"],
        mono: ["'DM Mono'", "monospace"],
      },
      boxShadow: {
        card: "0 2px 12px rgba(10, 22, 40, 0.08)",
        elevated: "0 8px 32px rgba(10, 22, 40, 0.12)",
      },
      borderRadius: {
        card: "16px",
        input: "12px",
        btn: "14px",
        pill: "100px",
      },
      spacing: {
        "safe-bottom": "env(safe-area-inset-bottom, 0px)",
        "bottom-nav": "68px",
        "top-bar": "56px",
      },
      minHeight: {
        "touch": "48px",
      },
      minWidth: {
        "touch": "48px",
      },
    },
  },
  plugins: [],
};

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
          primary: "#2A0F42",
          "primary-light": "#3E1763",
          accent: "#C893FF",
          "accent-hover": "#D8AEFF",
          violet: "#7C3AED",
          dark: "#160824",
        },
        surface: {
          page: "#F8F5FC",
          card: "#FFFFFF",
          "card-sub": "#F3EDFA",
          border: "#E8DEF5",
        },
        text: {
          primary: "#1A092A",
          secondary: "#6B5580",
          muted: "#9D88B3",
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

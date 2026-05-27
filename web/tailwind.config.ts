import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#ffffff",
        "bg-subtle": "#fafafa",
        "bg-inset": "#f4f4f5",
        border: "#e4e4e7",
        "border-strong": "#d4d4d8",
        text: "#09090b",
        "text-secondary": "#52525b",
        "text-tertiary": "#a1a1aa",
        ok: "#16a34a",
        running: "#2563eb",
        queued: "#a1a1aa",
        error: "#dc2626",
        p0: "#b91c1c",
        p1: "#c2410c",
        p2: "#a16207",
        p3: "#65a30d",
        accent: "#1e40af",
        "accent-bg": "#eff6ff",
        "accent-border": "#bfdbfe",
        "cta-bg": "#18181b",
        "cta-bg-hover": "#27272a",
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SF Mono", "Menlo", "monospace"],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "8px",
        lg: "12px",
      },
      fontSize: {
        xs: ["11px", "16px"],
        sm: ["12px", "18px"],
        base: ["14px", "22px"],
        lg: ["16px", "24px"],
        xl: ["20px", "28px"],
        "2xl": ["28px", "36px"],
        "3xl": ["32px", "40px"],
      },
      boxShadow: {
        sm: "0 1px 2px rgba(0, 0, 0, 0.04)",
        DEFAULT: "0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(0, 0, 0, 0.04)",
      },
    },
  },
  plugins: [],
};

export default config;

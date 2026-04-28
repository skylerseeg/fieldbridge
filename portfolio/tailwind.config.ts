import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0E0F0D",
        bone: "#EFE7DA",
        sage: "#A8B5A0",
      },
      fontFamily: {
        serif: ["var(--font-display-serif)", "Georgia", "Cambria", "Times New Roman", "serif"],
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      fontSize: {
        caption: ["0.75rem", { lineHeight: "1.1rem", letterSpacing: "0.08em" }],
        body: ["1rem", { lineHeight: "1.65rem" }],
        heading: ["clamp(2.25rem, 5vw, 3.75rem)", { lineHeight: "1.05" }],
        display: ["clamp(3rem, 9vw, 7rem)", { lineHeight: "0.95" }],
      },
      spacing: {
        "section-x": "clamp(1.5rem, 5vw, 4rem)",
        "section-y": "clamp(5rem, 12vw, 10rem)",
      },
      maxWidth: {
        section: "1280px",
      },
    },
  },
  plugins: [],
};

export default config;

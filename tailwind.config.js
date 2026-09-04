/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // 语义色调（tone）：值住在 app/globals.css 的 CSS 变量里，明暗自动切换。
        // 组件只写 text-tone-<族>-fg / bg-tone-<族>-bg / border-tone-<族>-border，不写 hex。
        overlay: "var(--overlay-backdrop)",
        tone: {
          sky: {
            fg: "var(--tone-sky-fg)",
            bg: "var(--tone-sky-bg)",
            border: "var(--tone-sky-border)",
          },
          green: {
            fg: "var(--tone-green-fg)",
            bg: "var(--tone-green-bg)",
            border: "var(--tone-green-border)",
          },
          amber: {
            fg: "var(--tone-amber-fg)",
            bg: "var(--tone-amber-bg)",
            border: "var(--tone-amber-border)",
          },
          teal: {
            fg: "var(--tone-teal-fg)",
            bg: "var(--tone-teal-bg)",
            border: "var(--tone-teal-border)",
          },
          rose: {
            fg: "var(--tone-rose-fg)",
            bg: "var(--tone-rose-bg)",
            border: "var(--tone-rose-border)",
          },
          lilac: {
            fg: "var(--tone-lilac-fg)",
            bg: "var(--tone-lilac-bg)",
            border: "var(--tone-lilac-border)",
          },
          neutral: {
            fg: "var(--tone-neutral-fg)",
            bg: "var(--tone-neutral-bg)",
            border: "var(--tone-neutral-border)",
          },
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [],
};

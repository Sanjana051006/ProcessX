/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // Tailwind's default opacity scale steps in fives, which is too coarse for
      // hairlines on white — 8% is a rule, 10% is a border, 15% is heavy. Every
      // integer is generated so `border-line/8` and friends resolve.
      opacity: Object.fromEntries(
        Array.from({ length: 101 }, (_, i) => [i, String(i / 100)]),
      ),
      colors: {
        // Every token resolves to a CSS variable holding an RGB triplet, so the
        // palette lives in one place (index.css) and Tailwind's opacity
        // utilities keep working through the `<alpha-value>` placeholder.
        bg: {
          DEFAULT: "rgb(var(--bg) / <alpha-value>)",
          tint: "rgb(var(--bg-tint) / <alpha-value>)",
        },
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          2: "rgb(var(--surface-2) / <alpha-value>)",
          3: "rgb(var(--surface-3) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          2: "rgb(var(--ink-2) / <alpha-value>)",
          3: "rgb(var(--ink-3) / <alpha-value>)",
          4: "rgb(var(--ink-4) / <alpha-value>)",
          // Legacy aliases, still referenced by the chart components.
          mid: "rgb(var(--ink-2) / <alpha-value>)",
          light: "rgb(var(--ink-3) / <alpha-value>)",
          faint: "rgb(var(--ink-4) / <alpha-value>)",
        },
        line: "rgb(var(--line) / <alpha-value>)",

        // The one interactive accent. Used for the current state, focus, links
        // and the brand mark — nowhere decorative.
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          2: "rgb(var(--accent-2) / <alpha-value>)",
          wash: "rgb(var(--accent-wash) / <alpha-value>)",
        },

        // Semantics. Health bands, deltas, severities.
        ok: "rgb(var(--ok) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        danger: "rgb(var(--danger) / <alpha-value>)",
        info: "rgb(var(--info) / <alpha-value>)",

        // Legacy names the existing charts and panels were written against.
        paper: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          soft: "rgb(var(--surface-2) / <alpha-value>)",
          sink: "rgb(var(--surface-3) / <alpha-value>)",
        },
        rule: "rgb(var(--line) / <alpha-value>)",
        red: {
          DEFAULT: "rgb(var(--danger) / <alpha-value>)",
          soft: "rgb(var(--red-soft) / <alpha-value>)",
        },
        band: {
          green: "rgb(var(--ok) / <alpha-value>)",
          amber: "rgb(var(--warn) / <alpha-value>)",
          red: "rgb(var(--danger) / <alpha-value>)",
          blue: "rgb(var(--info) / <alpha-value>)",
          violet: "rgb(var(--violet) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        // The micro-label: 9.5px at 0.18em tracking. Section eyebrows, table
        // headers, chart axes, chips.
        label: ["0.594rem", { lineHeight: "1", letterSpacing: "0.18em" }],
      },
      boxShadow: {
        xs: "var(--shadow-xs)",
        soft: "var(--shadow-sm)",
        card: "var(--shadow-md)",
        float: "var(--shadow-lg)",
        accent: "var(--shadow-accent)",
      },
      borderRadius: {
        "2xl": "16px",
        "3xl": "22px",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
        sweep: { from: { transform: "scaleX(0)" }, to: { transform: "scaleX(1)" } },
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.25" } },
        // The live-bus dot: a ring that expands and fades, once per beat.
        ping: {
          "0%": { transform: "scale(1)", opacity: "0.6" },
          "80%,100%": { transform: "scale(2.4)", opacity: "0" },
        },
        slidein: { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        rise: "rise 0.3s cubic-bezier(0.22,1,0.36,1) both",
        fade: "fade 0.35s ease both",
        sweep: "sweep 0.55s cubic-bezier(0.22,1,0.36,1) both",
        blink: "blink 1.2s ease-in-out infinite",
        ping: "ping 1.8s cubic-bezier(0,0,0.2,1) infinite",
        slidein: "slidein 0.28s cubic-bezier(0.22,1,0.36,1) both",
      },
    },
  },
  plugins: [],
};

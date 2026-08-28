/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // Tailwind's default opacity scale steps in fives, which is too coarse for
      // hairline rules on cream -- ink at 10% is visible, at 15% it is heavy.
      // Every integer is generated so `border-ink/12` and friends resolve.
      opacity: Object.fromEntries(
        Array.from({ length: 101 }, (_, i) => [i, String(i / 100)]),
      ),
      colors: {
        // Every token resolves to a CSS variable holding an RGB triplet, so the
        // palette lives in one place (index.css) and Tailwind's opacity
        // utilities keep working through the `<alpha-value>` placeholder.
        paper: {
          DEFAULT: "rgb(var(--paper) / <alpha-value>)",
          soft: "rgb(var(--paper-soft) / <alpha-value>)",
          sink: "rgb(var(--paper-sink) / <alpha-value>)",
        },
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          mid: "rgb(var(--ink-mid) / <alpha-value>)",
          light: "rgb(var(--ink-light) / <alpha-value>)",
          faint: "rgb(var(--ink-faint) / <alpha-value>)",
        },
        rule: {
          DEFAULT: "rgb(var(--rule) / <alpha-value>)",
          soft: "rgb(var(--rule-soft) / <alpha-value>)",
        },
        // The one accent, straight from the reference. Used for the current
        // state, the critical band and the brand mark -- nowhere decorative.
        red: {
          DEFAULT: "rgb(var(--red) / <alpha-value>)",
          soft: "rgb(var(--red-soft) / <alpha-value>)",
        },
        // Data bands. Deep and desaturated so they sit on cream without
        // vibrating, and distinguishable in greyscale by value alone.
        band: {
          green: "rgb(var(--green) / <alpha-value>)",
          amber: "rgb(var(--amber) / <alpha-value>)",
          red: "rgb(var(--red) / <alpha-value>)",
          blue: "rgb(var(--blue) / <alpha-value>)",
          violet: "rgb(var(--violet) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "Segoe UI", "sans-serif"],
        mono: ['"Geist Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
        serif: ["Georgia", "ui-serif", "serif"],
      },
      fontSize: {
        // The reference's micro-label: 9.6px at 0.3em tracking.
        label: ["0.6rem", { lineHeight: "1", letterSpacing: "0.3em" }],
        display: ["clamp(2.6rem, 6vw, 4.4rem)", { lineHeight: "0.88", letterSpacing: "-0.035em" }],
        headline: ["clamp(1.8rem, 3.4vw, 2.9rem)", { lineHeight: "0.95", letterSpacing: "-0.03em" }],
      },
      boxShadow: {
        capsule: "0 1px 2px rgba(10,10,10,0.04), 0 8px 32px -12px rgba(10,10,10,0.22)",
        lift: "0 2px 20px -8px rgba(10,10,10,0.18)",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        sweep: { from: { transform: "scaleX(0)" }, to: { transform: "scaleX(1)" } },
        blink: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.2" } },
        marquee: { from: { transform: "translateX(0)" }, to: { transform: "translateX(-50%)" } },
      },
      animation: {
        rise: "rise 0.32s cubic-bezier(0.22,1,0.36,1) both",
        sweep: "sweep 0.6s cubic-bezier(0.22,1,0.36,1) both",
        blink: "blink 1.1s ease-in-out infinite",
        marquee: "marquee 38s linear infinite",
      },
    },
  },
  plugins: [],
};

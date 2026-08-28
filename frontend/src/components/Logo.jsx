/**
 * The PX mark.
 *
 * A monogram built out of the thing the product is about: a process rail with a
 * junction on it. The `P` is a stem with a square bowl — deliberately squared,
 * not rounded, so it belongs to the same hard-edged family as the section rules
 * and the panels. The `X` is two crossing strokes sharing the P's baseline; the
 * descending one is red, which is the only accent in the system and here reads
 * as the branch a process takes when something goes wrong.
 *
 * Drawn on a 40x40 grid with a 4-unit stroke so it stays legible at 20px in the
 * navbar and at 96px on a splash. `currentColor` on the ink strokes lets the
 * same mark sit on paper or on an ink panel with no second asset.
 */
export default function Logo({ size = 28, className = "", accent = true }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      className={className}
      role="img"
      aria-label="ProcessX"
    >
      {/* P — stem */}
      <path
        d="M7 5.5V34.5"
        stroke="currentColor"
        strokeWidth="4.4"
        strokeLinecap="square"
      />
      {/* P — squared bowl, drawn as an open path so the counter stays hollow */}
      <path
        d="M7 7.7h9.4v9.6H7"
        stroke="currentColor"
        strokeWidth="4.4"
        strokeLinejoin="miter"
        strokeLinecap="butt"
      />
      {/* X — the ink diagonal */}
      <path
        d="M22.5 20.5L34.5 34.5"
        stroke="currentColor"
        strokeWidth="4.4"
        strokeLinecap="square"
      />
      {/* X — the accent diagonal. The branch that diverges. */}
      <path
        d="M34.5 20.5L22.5 34.5"
        stroke={accent ? "rgb(var(--red))" : "currentColor"}
        strokeWidth="4.4"
        strokeLinecap="square"
      />
      {/* The junction node where the two cross — the mark's optical centre. */}
      <circle cx="28.5" cy="27.5" r="2.6" fill="rgb(var(--paper))" />
      <circle
        cx="28.5"
        cy="27.5"
        r="2.6"
        stroke="currentColor"
        strokeWidth="1.6"
      />
    </svg>
  );
}

/** The mark plus the wordmark, for the navbar and the footer. */
export function Wordmark({ size = 26, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <Logo size={size} />
      <span className="font-extrabold tracking-[-0.045em] text-[17px] leading-none">
        PROCESS<span className="text-red">X</span>
      </span>
    </span>
  );
}

/**
 * The PX mark.
 *
 * A monogram built out of the thing the product is about: a process rail with a
 * junction on it. The `P` is a stem with a squared bowl; the `X` is two crossing
 * strokes sharing its baseline. The descending diagonal takes the accent, which
 * here reads as the branch a process takes when something goes wrong.
 *
 * Drawn on a 40x40 grid with rounded caps so it belongs to the same soft-edged
 * family as the cards, and stays legible at 20px in the navbar and at 96px on a
 * splash. `currentColor` on the ink strokes lets the same mark sit on a white
 * card or an ink panel with no second asset.
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
      <path d="M7.5 6V34" stroke="currentColor" strokeWidth="4.2" strokeLinecap="round" />
      {/* P — squared bowl, drawn as an open path so the counter stays hollow */}
      <path
        d="M7.5 8.1h8.6v9.2H7.5"
        stroke="currentColor"
        strokeWidth="4.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* X — the ink diagonal */}
      <path d="M23 21L34 33" stroke="currentColor" strokeWidth="4.2" strokeLinecap="round" />
      {/* X — the accent diagonal. The branch that diverges. */}
      <path
        d="M34 21L23 33"
        stroke={accent ? "rgb(var(--accent))" : "currentColor"}
        strokeWidth="4.2"
        strokeLinecap="round"
      />
      {/* The junction where the two cross — the mark's optical centre. */}
      <circle cx="28.5" cy="27" r="2.5" fill="rgb(var(--surface))" />
      <circle cx="28.5" cy="27" r="2.5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

/** The mark plus the wordmark, for headers and empty states. */
export function Wordmark({ size = 26, className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <Logo size={size} />
      <span className="text-[17px] font-bold leading-none tracking-[-0.035em]">
        Process<span className="text-accent">X</span>
      </span>
    </span>
  );
}

/** Formatters and scales. Every number in the UI passes through here, so a
 *  value is rendered the same way in a KPI tile, a table cell and a tooltip. */

export const hours = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${Number(v).toFixed(d)} h`;

export const num = (v, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d);

export const int = (v) =>
  v === null || v === undefined ? "—" : Math.round(Number(v)).toLocaleString("en-IN");

/** Rupees, Indian grouping. Compact past a lakh, where the exact digit count
 *  stops being the point and the magnitude starts being it. */
export const money = (v, compact = false) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Number(v);
  if (compact && Math.abs(n) >= 100000) return `₹${(n / 100000).toFixed(2)}L`;
  if (compact && Math.abs(n) >= 1000) return `₹${(n / 1000).toFixed(1)}k`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
};

export const pct = (v, d = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${(Number(v) * 100).toFixed(d)}%`;

/** A value that is already a percentage (contribution_pct is 0-100). */
export const pctRaw = (v, d = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${Number(v).toFixed(d)}%`;

/** Signed delta with an explicit direction word, for before/after tiles. */
export const delta = (v, fmt = hours) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const n = Number(v);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${fmt(Math.abs(n))}`;
};

/** `evidence_review` -> `Evidence review`. Mirrors the backend's `pretty`. */
export const pretty = (s) =>
  String(s ?? "")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());

/** Hours from t=0 (Monday 00:00) as a readable weekday + clock time. */
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const clock = (h) => {
  if (h === null || h === undefined) return "—";
  const total = Number(h);
  const day = DAYS[Math.floor(total / 24) % 7];
  const hour = Math.floor(total % 24);
  const min = Math.round((total % 1) * 60);
  return `${day} ${String(hour).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
};

/* -- colour -------------------------------------------------------------- */

/** The health bands the backend assigns, mapped to the data palette. */
export const BAND = {
  green: "rgb(var(--green))",
  amber: "rgb(var(--amber))",
  red: "rgb(var(--red))",
  grey: "rgb(var(--ink-faint))",
};

export const bandClass = {
  green: "text-band-green",
  amber: "text-band-amber",
  red: "text-red",
  grey: "text-ink-faint",
};

/** The five macro-stages, in lifecycle order, each with a fixed colour. Fixed
 *  rather than generated so a macro-stage is the same colour on every chart. */
export const MACRO_COLOR = {
  customer_onboarding: "rgb(var(--blue))",
  order_processing: "rgb(var(--green))",
  claims_processing: "rgb(var(--red))",
  support_resolution: "rgb(var(--amber))",
  invoice_approval: "rgb(var(--violet))",
};

/** Utilisation read as a load band: a stage over 0.8 is the interesting one. */
export const loadBand = (u) =>
  u === null || u === undefined ? "grey" : u > 0.8 ? "red" : u > 0.6 ? "amber" : "green";

export const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));

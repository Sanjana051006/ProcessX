/**
 * Column-span class maps for the bento grid.
 *
 * These have to be complete literal strings, not built by interpolation:
 * Tailwind's JIT scans source text for class names, so `lg:col-span-${n}` would
 * compile to nothing at all. Writing the table out once here is the price of
 * that, and it keeps every span in the app going through one place.
 *
 * The grid is 1 column on mobile, 6 on `sm`, 12 on `lg`. A tile therefore
 * declares what it wants at `lg` and at `sm`, and is simply full-width below
 * that — which is the correct answer on a phone for every tile in this app.
 */

export const LG = {
  1: "lg:col-span-1", 2: "lg:col-span-2", 3: "lg:col-span-3", 4: "lg:col-span-4",
  5: "lg:col-span-5", 6: "lg:col-span-6", 7: "lg:col-span-7", 8: "lg:col-span-8",
  9: "lg:col-span-9", 10: "lg:col-span-10", 11: "lg:col-span-11", 12: "lg:col-span-12",
};

export const SM = {
  1: "sm:col-span-1", 2: "sm:col-span-2", 3: "sm:col-span-3",
  4: "sm:col-span-4", 5: "sm:col-span-5", 6: "sm:col-span-6",
};

/** `span(4, 3)` -> the classes for a 4-of-12 tile that is 3-of-6 on tablet. */
export function span(lg = 4, sm = 6) {
  return `col-span-1 ${SM[sm] ?? SM[6]} ${LG[lg] ?? LG[4]}`;
}

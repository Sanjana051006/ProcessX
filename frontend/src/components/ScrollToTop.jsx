import { useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * Send every route change to the top of the page.
 *
 * React Router does not touch scroll position, and the browser's own
 * `scrollRestoration: "auto"` actively works against this app. The failure it
 * produced is specific and worth recording, because it looks like a routing bug
 * and is not:
 *
 *   1. Scroll the Dashboard down — the browser records that offset against the
 *      `/` history entry.
 *   2. Navigate to Simulation or Analyst. Those are locked-viewport pages, so
 *      the document collapses to one screen and the saved offset is clamped.
 *   3. Navigate back to the Dashboard. The document grows again and the browser
 *      re-applies its clamped offset — landing the reader in the middle of the
 *      page with the hero and the KPI row already scrolled past.
 *
 * So both halves are needed. Turning restoration off stops the browser
 * re-applying stale offsets; the explicit reset covers the ordinary case of
 * clicking a nav link while scrolled down.
 *
 * `useLayoutEffect` rather than `useEffect`: it runs before paint, so the new
 * page is never briefly drawn at the old offset.
 *
 * Every navigation goes to the top, including Back. With restoration disabled
 * the alternative is not "restore the old position" but "leave it wherever it
 * happened to be", which is the bug again — and on a three-page app, landing
 * predictably at the top beats keeping a place the reader has usually lost
 * track of anyway.
 */
export default function ScrollToTop() {
  const { pathname, hash } = useLocation();

  useLayoutEffect(() => {
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }
  }, []);

  useLayoutEffect(() => {
    // An in-page anchor is a deliberate request for a position; honour it.
    if (hash) return;
    window.scrollTo(0, 0);
  }, [pathname, hash]);

  return null;
}

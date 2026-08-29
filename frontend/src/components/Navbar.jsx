import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import Logo from "./Logo.jsx";
import { LiveDot } from "./ui.jsx";

const LINKS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/simulation", label: "Simulation" },
  { to: "/chat", label: "Analyst" },
];

/**
 * A floating capsule navbar.
 *
 * The rules it has to respect, in order of how often they get broken:
 *
 * 1. It never overlaps content. It is `fixed`, so it is out of flow — every
 *    page therefore reserves `--nav-space` at its top, and the fixed-viewport
 *    pages (simulation, chat) give that space to their grid rather than to the
 *    document, so content stops at the capsule instead of sliding under it.
 * 2. It stays inside the page gutters, centred in the same track the content
 *    uses, so on a narrow window it shrinks with the layout.
 * 3. It is legible over whatever scrolls beneath it: glass plus a hairline, and
 *    the shadow steps up once the page has scrolled.
 * 4. It is reachable by keyboard and announced correctly — a real <nav>, a
 *    landmark label, `aria-current` on the active link, and a skip link ahead
 *    of it in the tab order.
 */
export default function Navbar({ status, bus }) {
  const [scrolled, setScrolled] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // The fixed-viewport pages never scroll the window, so the capsule would
  // never pick up its scrolled state there. It sits over content from the
  // start on those, so it is held in the raised state.
  const raised = scrolled || pathname !== "/";

  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60]
                   focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:font-mono
                   focus:text-label focus:uppercase focus:text-white"
      >
        Skip to content
      </a>

      <div
        className="pointer-events-none fixed inset-x-0 z-50"
        style={{ top: "var(--nav-gap)" }}
      >
        <div className="mx-auto max-w-[1440px] px-3 sm:px-5">
          <nav
            aria-label="Primary"
            style={{ height: "var(--nav-h)" }}
            className={`glass pointer-events-auto flex items-center gap-2 rounded-full border
                        border-line/8 pl-3.5 pr-2 transition-shadow duration-300
                        ${raised ? "shadow-card" : "shadow-soft"}`}
          >
            <NavLink
              to="/"
              className="group flex shrink-0 items-center gap-2"
              aria-label="ProcessX home"
            >
              <Logo size={22} className="transition-transform group-hover:-rotate-6" />
              <span className="hidden text-[14.5px] font-bold leading-none tracking-[-0.035em] sm:inline">
                Process<span className="text-accent">X</span>
              </span>
            </NavLink>

            <span className="mx-1.5 hidden h-5 w-px shrink-0 bg-line/10 sm:block" aria-hidden />

            <ul className="flex min-w-0 items-center gap-0.5">
              {LINKS.map((l) => (
                <li key={l.to}>
                  <NavLink
                    to={l.to}
                    end={l.end}
                    className={({ isActive }) =>
                      `relative block whitespace-nowrap rounded-full px-3 py-2 font-mono
                       text-label uppercase transition-colors sm:px-3.5 ${
                         isActive ? "text-ink" : "text-ink-3 hover:text-ink"
                       }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <span
                            className="animate-fade absolute inset-0 -z-10 rounded-full bg-surface shadow-xs ring-1 ring-line/8"
                            aria-hidden
                          />
                        )}
                        {l.label}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>

            <div className="ml-auto flex min-w-0 items-center gap-1.5 pl-2">
              <BusPill bus={bus} />
              <RunPill status={status} />
            </div>
          </nav>
        </div>
      </div>
    </>
  );
}

/**
 * The event bus, at all times, on every page.
 *
 * It is in the navbar rather than on one dashboard tile because "this platform
 * is live" is a property of the whole application, not of one view — and
 * because the moment worth seeing is the count climbing while the user is
 * looking at something else entirely.
 */
function BusPill({ bus }) {
  if (!bus) return null;
  return (
    <span
      className="hidden items-center gap-1.5 rounded-full border border-line/8 bg-surface px-2.5 py-1.5 shadow-xs lg:flex"
      title={`Pub/Sub event bus — ${bus.backend ?? "memory"} backend, ${bus.count ?? 0} events delivered to this page`}
    >
      <LiveDot on={bus.connected} />
      <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-3">
        Bus
      </span>
      <span className="font-mono text-[9px] tabular-nums text-ink-4">{bus.count ?? 0}</span>
    </span>
  );
}

/** The world the whole UI is currently reading. It is the one piece of global
 *  state worth keeping visible at all times — every number on every page is
 *  relative to it, and reading the dashboard against the wrong run is the
 *  easiest mistake to make. */
function RunPill({ status }) {
  if (!status) {
    return (
      <span className="hidden items-center gap-2 rounded-full border border-line/8 px-2.5 py-1.5 md:flex">
        <span className="h-1.5 w-1.5 animate-blink rounded-full bg-ink-4" />
        <span className="font-mono text-label uppercase text-ink-4">Connecting</span>
      </span>
    );
  }
  if (status.error) {
    return (
      <span className="flex items-center gap-2 rounded-full border border-danger/25 bg-danger/[0.06] px-2.5 py-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-danger" />
        <span className="font-mono text-label uppercase text-danger">Offline</span>
      </span>
    );
  }
  return (
    <span
      className="flex max-w-[190px] items-center gap-2 rounded-full border border-line/8 bg-surface-3 px-2.5 py-1.5"
      title={`Current world: ${status.run_id} — ${status.label ?? ""}`}
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          status.scenario === "healthy" ? "bg-ok" : "bg-danger"
        }`}
      />
      <span className="truncate font-mono text-label uppercase text-ink-2">
        {status.run_id}
      </span>
    </span>
  );
}

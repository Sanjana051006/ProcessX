import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import Logo from "./Logo.jsx";

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
 *    page therefore reserves `--nav-space` at its top, and the chat page gives
 *    that space to its scroll container rather than to the page, so messages
 *    stop at the capsule instead of sliding under it.
 * 2. It stays inside the page gutters. The capsule is centred in a
 *    `max-w-6xl px-4` track, the same track the content uses, so on a narrow
 *    window it shrinks with the layout instead of touching the viewport edge.
 * 3. It is legible over whatever scrolls beneath it. Translucent plus a backdrop
 *    blur is not enough on a busy chart, so the ground opacity and the border
 *    both step up once the page has scrolled.
 * 4. It is reachable by keyboard and announced correctly: a real <nav>, a real
 *    landmark label, `aria-current` on the active link, and a skip link ahead of
 *    it in the tab order.
 */
export default function Navbar({ status }) {
  const [scrolled, setScrolled] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // The chat page does not scroll the window, so the capsule would never pick
  // up its scrolled state there. It sits over a solid panel instead, so it is
  // held in the solid state from the start.
  const solid = scrolled || pathname === "/chat";

  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60]
                   focus:rounded-full focus:bg-ink focus:px-4 focus:py-2 focus:text-paper
                   focus:font-mono focus:text-label focus:uppercase"
      >
        Skip to content
      </a>

      <div
        className="fixed inset-x-0 z-50 pointer-events-none"
        style={{ top: "var(--nav-gap)" }}
      >
        <div className="mx-auto max-w-6xl px-4">
          <nav
            aria-label="Primary"
            style={{ height: "var(--nav-h)" }}
            className={`pointer-events-auto flex items-center gap-2 rounded-full pl-4 pr-2
                        border transition-[background-color,border-color,box-shadow] duration-300
                        ${
                          solid
                            ? "bg-paper/92 border-ink/14 shadow-capsule"
                            : "bg-paper/70 border-ink/8 shadow-none"
                        }`}
          >
            <div className="backdrop-blur-xl absolute inset-0 rounded-full -z-10" />

            <NavLink
              to="/"
              className="flex items-center gap-2 shrink-0 group"
              aria-label="ProcessX home"
            >
              <Logo size={24} className="transition-transform group-hover:-rotate-6" />
              <span className="hidden sm:inline font-extrabold tracking-[-0.045em] text-[15px] leading-none">
                PROCESS<span className="text-red">X</span>
              </span>
            </NavLink>

            <span className="mx-1 h-5 w-px bg-ink/12 shrink-0" aria-hidden />

            <ul className="flex items-center gap-0.5 min-w-0">
              {LINKS.map((l) => (
                <li key={l.to}>
                  <NavLink
                    to={l.to}
                    end={l.end}
                    className={({ isActive }) =>
                      `relative block rounded-full px-3 sm:px-4 py-2 font-mono text-label uppercase
                       transition-colors whitespace-nowrap ${
                         isActive
                           ? "text-paper"
                           : "text-ink-mid hover:text-ink"
                       }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {isActive && (
                          <span
                            className="absolute inset-0 rounded-full bg-ink -z-10 animate-rise"
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

            <div className="ml-auto flex items-center gap-2 pl-2 min-w-0">
              <RunPill status={status} />
            </div>
          </nav>
        </div>
      </div>
    </>
  );
}

/** The world the whole UI is currently reading. It is the one piece of global
 *  state worth keeping visible at all times — every number on every page is
 *  relative to it, and reading the dashboard against the wrong run is the
 *  easiest mistake to make. */
function RunPill({ status }) {
  if (!status) {
    return (
      <span className="hidden md:flex items-center gap-2 rounded-full border border-ink/12 px-3 py-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-ink-faint animate-blink" />
        <span className="font-mono text-label uppercase text-ink-faint">Connecting</span>
      </span>
    );
  }
  if (status.error) {
    return (
      <span className="flex items-center gap-2 rounded-full border border-red/30 bg-red/8 px-3 py-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-red" />
        <span className="font-mono text-label uppercase text-red">Offline</span>
      </span>
    );
  }
  return (
    <span
      className="flex items-center gap-2 rounded-full border border-ink/12 bg-paper-sink/50 px-3 py-1.5 max-w-[210px]"
      title={`Current run: ${status.run_id}`}
    >
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          status.scenario === "healthy" ? "bg-band-green" : "bg-red"
        }`}
      />
      <span className="font-mono text-label uppercase text-ink-mid truncate">
        {status.run_id}
      </span>
    </span>
  );
}

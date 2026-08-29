/**
 * The nine-panel progress rail.
 *
 * It is a rail rather than a row of tabs because the panels are a sequence with
 * a direction: the world produces the features M1 reads, M1's residual feeds M2
 * and M4, the agent sits between M3 and M4, and M5/M6 only exist once the agent
 * has concluded. Tabs would say "pick one"; a rail says "this happened, then
 * this".
 *
 * Every node stays clickable — stepping is the primary interaction, but jumping
 * straight to M6 is a reasonable thing to want and disabling it would be
 * pedantry.
 *
 * Sized to a single 46px band. The simulation page spends its height on the
 * panel, so the rail earns very little of it: a 24px node, a label that is
 * hidden below `md`, and no vertical padding beyond what the ring needs.
 */
export default function StepRail({ steps, index, onSelect }) {
  return (
    <ol className="flex min-w-0 items-start">
      {steps.map((s, i) => {
        const isCurrent = i === index;
        const isPast = i < index;
        return (
          <li key={s.key} className="flex min-w-0 flex-1 items-start">
            <button
              type="button"
              onClick={() => onSelect(i)}
              aria-current={isCurrent ? "step" : undefined}
              title={s.title}
              className="group flex min-w-0 flex-1 flex-col items-center gap-1"
            >
              <span className="flex w-full items-center">
                <span
                  className={`h-px flex-1 transition-colors ${
                    i === 0 ? "bg-transparent" : isPast || isCurrent ? "bg-accent" : "bg-line/14"
                  }`}
                />
                <span
                  className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border
                              font-mono text-[8.5px] font-semibold uppercase transition-all
                              ${
                                isCurrent
                                  ? "scale-110 border-accent bg-accent text-white shadow-accent"
                                  : isPast
                                    ? "border-accent/50 bg-surface text-accent"
                                    : "border-line/14 bg-surface text-ink-4 group-hover:border-line/35"
                              }`}
                >
                  {s.model === "SIM"
                    ? "◆"
                    : s.model === "AGENT"
                      ? "◉"
                      : s.model === "APPLY"
                        ? "✓"
                        : s.model}
                </span>
                <span
                  className={`h-px flex-1 transition-colors ${
                    i === steps.length - 1 ? "bg-transparent" : isPast ? "bg-accent" : "bg-line/14"
                  }`}
                />
              </span>
              <span
                className={`hidden w-full truncate px-1 text-center font-mono text-[8.5px] uppercase
                            leading-none tracking-[0.1em] transition-colors md:block ${
                              isCurrent
                                ? "text-ink"
                                : isPast
                                  ? "text-ink-3"
                                  : "text-ink-4 group-hover:text-ink-3"
                            }`}
              >
                {s.title}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

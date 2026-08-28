/**
 * The nine-panel progress rail.
 *
 * It is a rail rather than a row of tabs because the panels are a sequence with
 * a direction: the world produces the features M1 reads, M1's residual feeds M2
 * and M4, the agent sits between M3 and M4, and M5/M6 only exist once the agent
 * has concluded. Tabs would say "pick one"; a rail says "this happened, then
 * this".
 *
 * Every node stays clickable — stepping is the primary interaction but jumping
 * straight to M6 is a reasonable thing to want, and disabling it would be
 * pedantry.
 */
export default function StepRail({ steps, index, onSelect }) {
  return (
    <div className="overflow-x-auto pb-2">
      <ol className="flex min-w-[720px] items-start gap-0">
        {steps.map((s, i) => {
          const isCurrent = i === index;
          const isPast = i < index;
          return (
            <li key={s.key} className="flex flex-1 items-start">
              <button
                type="button"
                onClick={() => onSelect(i)}
                aria-current={isCurrent ? "step" : undefined}
                className="group flex flex-1 flex-col items-center gap-2 px-1"
              >
                <span className="flex w-full items-center">
                  {/* Connector in */}
                  <span
                    className={`h-px flex-1 transition-colors ${
                      i === 0 ? "bg-transparent" : isPast || isCurrent ? "bg-ink" : "bg-ink/16"
                    }`}
                  />
                  <span
                    className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border
                                font-mono text-[9px] font-semibold uppercase transition-all
                                ${
                                  isCurrent
                                    ? "scale-110 border-ink bg-ink text-paper shadow-lift"
                                    : isPast
                                      ? "border-ink bg-paper text-ink"
                                      : "border-ink/20 bg-paper text-ink-faint group-hover:border-ink/50"
                                }`}
                  >
                    {s.model === "SIM" ? "◆" : s.model === "AGENT" ? "◉" : s.model === "APPLY" ? "✓" : s.model}
                  </span>
                  {/* Connector out */}
                  <span
                    className={`h-px flex-1 transition-colors ${
                      i === steps.length - 1
                        ? "bg-transparent"
                        : isPast
                          ? "bg-ink"
                          : "bg-ink/16"
                    }`}
                  />
                </span>
                <span
                  className={`text-center font-mono text-[8.5px] uppercase leading-tight tracking-[0.14em]
                              transition-colors ${
                                isCurrent
                                  ? "text-ink"
                                  : isPast
                                    ? "text-ink-mid"
                                    : "text-ink-faint group-hover:text-ink-mid"
                              }`}
                >
                  {s.title}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

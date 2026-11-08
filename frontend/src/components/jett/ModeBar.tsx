import { useMode } from "@/hooks/use-mode";
import { snapLabel, type Snap, type View } from "@/lib/data";
import { cn } from "@/lib/utils";

const VIEWS: { k: View; l: string; hint: string }[] = [
  { k: "showdown", l: "Showdown", hint: "Results revealed: see whether the sharps were right" },
  {
    k: "live",
    l: "Live",
    hint: "Results hidden: the prediction only, as a live product would show it",
  },
];
const SNAPS: Snap[] = ["24h", "7d"];

function Segment<T extends string>({
  label,
  options,
  value,
  onPick,
}: {
  label: string;
  options: { k: T; l: string }[];
  value: T;
  onPick: (k: T) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={label}>
      <span className="text-xs uppercase tracking-widest text-text-3">{label}</span>
      <div className="flex rounded-full border border-border bg-panel p-1">
        {options.map((o) => (
          <button
            key={o.k}
            type="button"
            aria-pressed={value === o.k}
            onClick={() => onPick(o.k)}
            className={cn(
              "min-h-9 rounded-full px-4 text-sm transition-colors",
              value === o.k
                ? "bg-gold font-semibold text-primary-foreground"
                : "text-text-2 hover:text-gold-light",
            )}
          >
            {o.l}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The two app-wide toggles: Showdown/Live and how long before close the markets are frozen. */
export function ModeBar() {
  const { view, at, set } = useMode();
  return (
    <div className="space-y-2 rounded-xl border border-border bg-panel/60 px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <Segment label="Mode" options={VIEWS} value={view} onPick={(k) => set({ view: k })} />
        <Segment
          label="Frozen"
          options={SNAPS.map((k) => ({ k, l: `${snapLabel[k]} before close` }))}
          value={at}
          onPick={(k) => set({ at: k })}
        />
      </div>
      <p className="text-xs text-text-3">{VIEWS.find((v) => v.k === view)?.hint}</p>
    </div>
  );
}

/** Just the snapshot toggle, for pages where Showdown/Live doesn't apply (the Scoreboard). */
export function SnapToggle() {
  const { at, set } = useMode();
  return (
    <Segment
      label="Frozen"
      options={SNAPS.map((k) => ({ k, l: `${snapLabel[k]} before close` }))}
      value={at}
      onPick={(k) => set({ at: k })}
    />
  );
}

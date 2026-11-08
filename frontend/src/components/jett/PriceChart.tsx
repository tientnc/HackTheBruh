import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { View } from "@/lib/data";

const day = (ms: number) =>
  new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/**
 * Polymarket-style chart of the YES chance over time.
 * Live mode stops at the snapshot (no peeking); Showdown shows the rest and marks the snapshot.
 */
export function PriceChart({
  points,
  snapshotAt,
  view,
  outcome,
}: {
  points: [number, number][];
  snapshotAt: string;
  view: View;
  outcome?: "yes" | "no" | undefined;
}) {
  const snap = new Date(snapshotAt).getTime();
  const data = points
    .map(([t, p]) => ({ t: t * 1000, p: Math.round(p * 1000) / 10 }))
    .filter((d) => view === "showdown" || d.t <= snap);
  if (data.length < 2)
    return <p className="text-sm text-text-3">Not enough price history for this market.</p>;
  const last = data[data.length - 1]!;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="font-display text-4xl text-foreground">{Math.round(last.p)}%</span>
        <span className="text-sm text-text-2">
          chance of YES{" "}
          {view === "live"
            ? "at this moment"
            : outcome
              ? `at close · resolved ${outcome.toUpperCase()}`
              : "at close"}
        </span>
      </div>
      <div
        className="h-72"
        role="img"
        aria-label={`YES price over time, ending at ${Math.round(last.p)} percent`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ left: -10, right: 12, top: 10 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={day}
              stroke="var(--text-3)"
              fontSize={12}
              minTickGap={40}
            />
            <YAxis
              domain={[0, 100]}
              ticks={[0, 25, 50, 75, 100]}
              unit="%"
              stroke="var(--text-3)"
              fontSize={12}
            />
            <Tooltip
              labelFormatter={(v) => day(Number(v))}
              formatter={(v) => [`${v}%`, "YES"]}
              contentStyle={{
                background: "var(--panel)",
                border: "1px solid var(--border)",
                color: "var(--foreground)",
              }}
            />
            {view === "showdown" && last.t > snap && (
              <ReferenceArea
                x1={snap}
                x2={last.t}
                fill="var(--card-paper)"
                fillOpacity={0.06}
                ifOverflow="hidden"
              />
            )}
            {view === "showdown" && (
              <ReferenceLine
                x={snap}
                stroke="var(--gold-light)"
                strokeDasharray="4 4"
                label={{
                  value: "Snapshot",
                  position: "insideTopRight",
                  fill: "var(--gold-light)",
                  fontSize: 12,
                }}
              />
            )}
            <Area
              type="stepAfter"
              dataKey="p"
              stroke="var(--gold)"
              strokeWidth={2}
              fill="var(--gold)"
              fillOpacity={0.12}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

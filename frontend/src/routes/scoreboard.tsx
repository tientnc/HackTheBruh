import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend as RLegend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { GapCard } from "@/components/jett/GapCard";
import { SnapToggle } from "@/components/jett/ModeBar";
import { GoldLink, Panel } from "@/components/jett/Shell";
import { TiersBanner } from "@/components/jett/TiersBanner";
import { FollowTheMoney } from "@/components/jett/FollowTheMoney";
import { useMode } from "@/hooks/use-mode";
import {
  callResult,
  fmtDate,
  fmtDateYear,
  getMarkets,
  getResearchMarkets,
  ratingSnapshot,
  scoreboard,
  skillGap,
  snapLabel,
  tiersPending,
  type GapBucket,
  type Snap,
} from "@/lib/data";

export const Route = createFileRoute("/scoreboard")({
  loaderDeps: ({ search }) => ({ at: ((search as { at?: Snap }).at ?? "24h") as Snap }),
  loader: async ({ deps }) => {
    const [markets, research] = await Promise.all([getMarkets(deps.at), getResearchMarkets()]);
    return { markets, research };
  },
  head: () => ({
    meta: [
      { title: "Scoreboard · Jett Showdown" },
      {
        name: "description",
        content:
          "The track record: on resolved markets, did the proven traders beat the crowd's price?",
      },
      { property: "og:title", content: "Scoreboard · Jett Showdown" },
      {
        property: "og:description",
        content:
          "The track record: on resolved markets, did the proven traders beat the crowd's price?",
      },
    ],
  }),
  component: Scoreboard,
});

const pct = (x: number | null) => (x === null ? "—" : `${Math.round(x * 100)}%`);

function Stat({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <Panel className="space-y-2">
      <p className="text-sm text-text-3">{label}</p>
      <p className="font-display text-5xl text-foreground">{value}</p>
      <div className="text-sm text-text-2">{children}</div>
    </Panel>
  );
}

function bigGapReading(b: GapBucket | undefined): string | null {
  if (!b || b.sharpSideWon === null || b.priceImplied === null) return null;
  const diff = b.sharpSideWon - b.priceImplied;
  const few = b.tables < 10 ? ` Only ${b.tables} tables, so treat this with care.` : "";
  if (diff > 0.05)
    return `On big gaps, the sharps' side won ${pct(b.sharpSideWon)} of the time, more than the ${pct(b.priceImplied)} the price expected.${few}`;
  if (diff < -0.05)
    return `On big gaps, the sharps' side won only ${pct(b.sharpSideWon)} of the time, less than the ${pct(b.priceImplied)} the price expected.${few}`;
  return `On big gaps, the sharps' side won ${pct(b.sharpSideWon)} of the time, about what the price expected (${pct(b.priceImplied)}).${few}`;
}

function Scoreboard() {
  const { markets, research } = Route.useLoaderData();
  const { at } = useMode();
  const s = scoreboard(markets);
  const hasGaps = s.buckets.some((b) => b.tables > 0);
  const chart = s.buckets
    .filter((b) => b.tables > 0)
    .map((b) => ({
      name: b.label.replace(/ \(.*\)/, ""),
      sharps: Math.round((b.sharpSideWon ?? 0) * 100),
      price: Math.round((b.priceImplied ?? 0) * 100),
    }));
  const reading = bigGapReading(s.buckets[2]);

  return (
    <div className="space-y-12">
      <section className="space-y-4">
        <p className="caption">Track record</p>
        <h1 className="text-5xl leading-tight md:text-6xl">Scoreboard</h1>
        <p className="max-w-3xl text-text-2">
          Every table here has already ended. We froze each one {snapLabel[at]} before it closed,
          using only what was known then, and checked who was right: the crowd's price, or the
          proven traders.
        </p>
        <p className="text-sm text-text-3">
          Wallet ratings use {ratingSnapshot.markets} historical finance markets and were frozen on{" "}
          {fmtDateYear(ratingSnapshot.asOf)} UTC.
        </p>
        <SnapToggle />
        <TiersBanner />
      </section>

      <section aria-labelledby="headline" className="space-y-4">
        <h2 id="headline" className="sr-only">
          Headline results
        </h2>
        <div className="grid gap-6 md:grid-cols-3">
          <Stat
            label="The crowd's favourite won"
            value={pct(s.crowd.favouriteRight / Math.max(1, s.crowd.favouriteTables))}
          >
            {s.crowd.favouriteRight} of {s.crowd.favouriteTables} tables. The favourite is whichever
            side cost more than 50¢. This is the bar the sharps have to beat.
          </Stat>
          <Stat
            label="The sharps' calls that were right"
            value={s.calls.made ? pct(s.calls.right / s.calls.made) : "—"}
          >
            {s.calls.made
              ? `${s.calls.right} of ${s.calls.made} calls. A call needs enough skilled money leaning clearly one way.`
              : tiersPending
                ? "Appears when the wallet ratings arrive."
                : "No table had enough skilled money for a call."}
          </Stat>
          <Stat
            label="The crowd's favourite, on those same tables"
            value={s.calls.made ? pct(s.calls.crowdRightSameTables / s.calls.made) : "—"}
          >
            {s.calls.made
              ? "The fair comparison: same tables, same moment. If the sharps aren't above this, following them adds nothing."
              : "The fair comparison for the sharps' calls, once there are some."}
          </Stat>
        </div>
        <p className="text-sm text-text-3">
          Why winning alone can mislead: favourites usually win, so anyone backing them looks good.
          The real test is below: does the sharps' side win more often than its price expected?
        </p>
      </section>

      <FollowTheMoney markets={markets} at={at} />

      <Panel className="space-y-6">
        <div>
          <h2 className="text-2xl text-gold-light">
            Does a bigger skill gap mean a better signal?
          </h2>
          <p className="text-sm text-text-3">
            For each size of gap: how often the side the sharps favoured actually won, against how
            often its price said it would.
          </p>
        </div>
        {hasGaps ? (
          <>
            <div
              className="h-72"
              role="img"
              aria-label="Sharps' side win rate against price-implied chance, by skill gap size"
            >
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart} margin={{ left: -10, right: 10 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" stroke="var(--text-3)" fontSize={12} />
                  <YAxis domain={[0, 100]} unit="%" stroke="var(--text-3)" fontSize={12} />
                  <Tooltip
                    formatter={(v) => `${v}%`}
                    contentStyle={{
                      background: "var(--panel)",
                      border: "1px solid var(--border)",
                      color: "var(--foreground)",
                    }}
                  />
                  <RLegend />
                  <Bar
                    dataKey="sharps"
                    name="Sharps' side won"
                    fill="var(--gold)"
                    isAnimationActive={false}
                  />
                  <Bar
                    dataKey="price"
                    name="Price expected"
                    fill="var(--card-paper)"
                    isAnimationActive={false}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-text-3">
                  <tr className="border-b border-border">
                    <th className="py-2 font-medium">Skill gap</th>
                    <th className="py-2 text-right font-medium">Tables</th>
                    <th className="py-2 text-right font-medium">Sharps' side won</th>
                    <th className="py-2 text-right font-medium">Price expected</th>
                  </tr>
                </thead>
                <tbody>
                  {s.buckets.map((b) => (
                    <tr key={b.label} className="border-b border-border/60 text-text-2">
                      <th scope="row" className="py-2.5 font-normal text-foreground">
                        {b.label}
                      </th>
                      <td className="py-2.5 text-right">{b.tables}</td>
                      <td className="py-2.5 text-right">{pct(b.sharpSideWon)}</td>
                      <td className="py-2.5 text-right">{pct(b.priceImplied)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {reading && <p className="text-gold-light">{reading}</p>}
          </>
        ) : (
          <p className="text-text-2">
            {tiersPending
              ? "This fills in automatically when the wallet ratings arrive: every table needs skilled money to have a skill gap."
              : "No table has skilled money yet, so there are no skill gaps to compare."}
          </p>
        )}
      </Panel>

      {s.notable.length > 0 && (
        <section aria-labelledby="notable" className="space-y-4">
          <div>
            <h2 id="notable" className="text-3xl text-gold-light">
              Notable hands
            </h2>
            <p className="text-sm text-text-3">
              The biggest disagreements with the crowd, and how they turned out.
            </p>
          </div>
          <ul className="grid gap-4 md:grid-cols-2">
            {s.notable.map((m) => {
              const r = callResult(m);
              return (
                <li key={m.id}>
                  <Link
                    to="/table/$id"
                    params={{ id: m.id }}
                    search={{ view: "showdown", at }}
                    className="flex gap-4 rounded-xl border border-border bg-panel p-4 transition-colors hover:border-gold"
                  >
                    <GapCard gap={skillGap(m)} size="sm" tilt={-4} />
                    <span className="min-w-0 space-y-1">
                      <span className="block font-semibold text-foreground">{m.question}</span>
                      <span className="block text-sm text-text-2">
                        {m.call === "YES" || m.call === "NO"
                          ? `Sharps called ${m.call}`
                          : "No sharp call"}{" "}
                        · Result {m.outcome?.toUpperCase()}
                      </span>
                      <span className="block text-sm font-semibold text-gold-light">
                        {r === "hit"
                          ? "The sharps were right"
                          : r === "miss"
                            ? "The sharps were wrong"
                            : "Not enough skilled money to call"}
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <Panel className="space-y-2">
        <h2 className="text-xl text-gold-light">How to read these numbers</h2>
        <p className="text-text-2">
          The crowd's Brier score here is {s.crowd.brier.toFixed(3)} across {s.tables} tables (0 is
          perfect, lower is better). Following the sharps is only worth it if their side wins more
          often than its price expected, consistently, across many tables. Small samples can mislead
          in either direction.
        </p>
        <Link
          to="/how-to-play"
          className="inline-block text-sm text-text-2 underline underline-offset-4 hover:text-gold-light"
        >
          How to read a table
        </Link>
      </Panel>

      <Panel className="space-y-3">
        <h2 className="text-xl text-gold-light">Research database</h2>
        {research.status === "connected" && (
          <p className="text-sm text-text-2">
            Supabase · Read only
            {research.markets.length === 0 && " · No published research markets yet"}
          </p>
        )}
        {research.status === "unconfigured" && (
          <p className="text-sm text-text-2">Supabase is not configured for this deployment.</p>
        )}
        {research.status === "unavailable" && (
          <p className="text-sm text-text-2">Supabase is temporarily unavailable.</p>
        )}
        {research.status === "connected" && research.markets.length > 0 && (
          <ul className="divide-y divide-border">
            {research.markets.map((market) => (
              <li
                key={`${market.dataset_key}:${market.market_id}`}
                className="flex flex-wrap justify-between gap-2 py-3"
              >
                <span>{market.question}</span>
                <span className="text-text-2">
                  {market.yes_outcome === 1 ? "YES" : "NO"} ·{" "}
                  {fmtDate(new Date(market.label_available_at * 1000).toISOString())}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <div className="flex justify-center">
        <GoldLink to="/">Back to the Lobby</GoldLink>
      </div>
    </div>
  );
}

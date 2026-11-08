import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  callResult,
  cents,
  chipUnit,
  featured,
  fmtDateYear,
  getMarkets,
  predictionText,
  skillGap,
  skilledYesShare,
  snapLabel,
  verdict,
  type Market,
  type Snap,
} from "@/lib/data";
import { useMode } from "@/hooks/use-mode";
import { ModeBar } from "@/components/jett/ModeBar";
import { Sparkline } from "@/components/jett/Sparkline";
import { PokerTable } from "@/components/jett/PokerTable";
import { Legend } from "@/components/jett/Chips";
import { GapCard } from "@/components/jett/GapCard";
import { TiersBanner } from "@/components/jett/TiersBanner";
import { goldLinkClass } from "@/components/jett/Shell";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  loaderDeps: ({ search }) => ({ at: ((search as { at?: Snap }).at ?? "24h") as Snap }),
  loader: ({ deps }) => getMarkets(deps.at),
  head: () => ({
    meta: [
      { title: "Lobby · Jett Showdown" },
      {
        name: "description",
        content:
          "Real 2026 prediction markets, frozen 24 hours before they closed: where the money sat, then the showdown.",
      },
      { property: "og:title", content: "Lobby · Jett Showdown" },
      {
        property: "og:description",
        content:
          "Real 2026 prediction markets, frozen 24 hours before they closed: where the money sat, then the showdown.",
      },
    ],
  }),
  component: Lobby,
});

const PAGE = 12;
const SORTS = [
  { k: "gap", l: "Skill gap" },
  { k: "volume", l: "Volume" },
  { k: "recent", l: "Closing date" },
] as const;

function resultText(m: Market): string {
  if (!m.outcome) return "";
  const r = callResult(m);
  const tail = r === "hit" ? "Sharps called it" : r === "miss" ? "Sharps missed" : "No sharp call";
  return `Result: ${m.outcome.toUpperCase()} · ${tail}`;
}

function Lobby() {
  const markets = Route.useLoaderData();
  const { view, at } = useMode();
  const live = view === "live";
  const top = featured(markets);
  const cats = useMemo(
    () => ["All", ...Array.from(new Set(markets.map((m) => m.category))).sort()],
    [markets],
  );
  const [cat, setCat] = useState("All");
  const [sort, setSort] = useState<(typeof SORTS)[number]["k"]>("gap");
  const [shown, setShown] = useState(PAGE);

  const others = useMemo(() => {
    const absGap = (m: Market) => Math.abs(skillGap(m) ?? -1);
    const list = markets.filter((m) => m.id !== top.id && (cat === "All" || m.category === cat));
    return list.sort((a, b) =>
      sort === "gap"
        ? absGap(b) - absGap(a) || b.volume_usd - a.volume_usd
        : sort === "volume"
          ? b.volume_usd - a.volume_usd
          : b.closes_at.localeCompare(a.closes_at),
    );
  }, [markets, top.id, cat, sort]);

  const pill = (on: boolean) =>
    cn(
      "rounded-full border px-3 py-1 text-sm transition-colors",
      on
        ? "border-gold bg-gold font-semibold text-primary-foreground"
        : "border-border text-text-2 hover:border-gold",
    );

  return (
    <div className="space-y-12">
      <section className="space-y-4">
        <ModeBar />
        <p className="caption">
          {live
            ? `Live · ${top.category} · Closes ${fmtDateYear(top.closes_at)} · in ${snapLabel[at]}`
            : `Replay · ${top.category} · Frozen ${snapLabel[at]} before close · ${fmtDateYear(top.closes_at)}`}
        </p>
        <h1 className="max-w-4xl text-4xl leading-tight md:text-6xl">{top.question}</h1>
        <p className="max-w-3xl text-text-2">
          {live
            ? `Every table is a real Polymarket market from 2026, shown as it stood ${snapLabel[at]} before it closed. You see the money and the sharps' prediction, but not the result, just as you would on a live market.`
            : `Every table is a real Polymarket market from 2026, frozen ${snapLabel[at]} before it closed. See where the money sat, then the showdown.`}
        </p>
        <TiersBanner />
        <Legend unit={chipUnit(top)} />
      </section>

      <PokerTable m={top} view={view} />
      <div className="flex justify-center">
        <Link to="/table/$id" params={{ id: top.id }} className={goldLinkClass}>
          See every hand at this table
        </Link>
      </div>

      <section className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-3xl text-gold-light">Other tables</h2>
            <p className="text-sm text-text-3">
              {markets.length} {live ? "markets" : "resolved markets"} · each frozen {snapLabel[at]}{" "}
              before close
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:items-end">
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
              {cats.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-pressed={cat === c}
                  className={pill(cat === c)}
                  onClick={() => {
                    setCat(c);
                    setShown(PAGE);
                  }}
                >
                  {c}
                </button>
              ))}
            </div>
            <div
              className="flex flex-wrap items-center gap-2"
              role="group"
              aria-label="Sort tables"
            >
              <span className="text-sm text-text-3">Sort:</span>
              {SORTS.map((s) => (
                <button
                  key={s.k}
                  type="button"
                  aria-pressed={sort === s.k}
                  className={pill(sort === s.k)}
                  onClick={() => {
                    setSort(s.k);
                    setShown(PAGE);
                  }}
                >
                  {s.l}
                </button>
              ))}
            </div>
          </div>
        </div>
        {others.length === 0 ? (
          <p className="text-text-3">No other tables in this category.</p>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {others.slice(0, shown).map((m) => {
              const g = skillGap(m);
              const share = skilledYesShare(m);
              return (
                <Link
                  key={m.id}
                  to="/table/$id"
                  params={{ id: m.id }}
                  className="group flex gap-4 rounded-xl border border-border bg-panel p-5 transition-colors hover:border-gold"
                >
                  <div className="shrink-0 pt-1">
                    <GapCard gap={g} size="sm" tilt={-4} />
                  </div>
                  <div className="min-w-0 space-y-2">
                    <p className="text-[11px] uppercase tracking-widest text-text-3">
                      {m.category} · {live ? "Closes " : ""}
                      {fmtDateYear(m.closes_at)}
                    </p>
                    <h3 className="font-sans text-base font-semibold text-foreground group-hover:text-gold-light">
                      {m.question}
                    </h3>
                    <p className="text-sm text-text-2">
                      House: YES {cents(m.yes_price)} ·{" "}
                      {share === null
                        ? "Sharps: no rated money"
                        : `Sharps: ${Math.round(share * 100)}% on YES`}
                    </p>
                    {m.spark && <Sparkline points={m.spark} />}
                    <p className="text-sm text-gold-light">{verdict(g)}</p>
                    {live ? (
                      <p className="text-xs font-semibold uppercase tracking-wider text-text-2">
                        Prediction: {predictionText(m)}
                      </p>
                    ) : (
                      m.outcome && (
                        <p className="text-xs font-semibold uppercase tracking-wider text-text-2">
                          {resultText(m)}
                        </p>
                      )
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
        {others.length > shown && (
          <div className="flex justify-center">
            <button
              type="button"
              className="rounded-full border border-gold px-5 py-2.5 text-sm font-semibold text-gold-light hover:bg-gold hover:text-primary-foreground"
              onClick={() => setShown((n) => n + PAGE)}
            >
              Show more tables ({others.length - shown} left)
            </button>
          </div>
        )}
      </section>
    </div>
  );
}

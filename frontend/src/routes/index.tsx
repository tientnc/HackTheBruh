import { createFileRoute, Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { cents, featured, fmtDate, getMarkets, skillGap, skilledYesShare, verdict } from "@/lib/data";
import { PokerTable } from "@/components/jett/PokerTable";
import { Legend } from "@/components/jett/Chips";
import { GapCard } from "@/components/jett/GapCard";
import { goldLinkClass } from "@/components/jett/Shell";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  loader: () => getMarkets(),
  head: () => ({
    meta: [
      { title: "Lobby · Jett Showdown" },
      { name: "description", content: "Tonight's highest-stakes prediction markets, with skilled, unskilled and new money laid out on the table." },
      { property: "og:title", content: "Lobby · Jett Showdown" },
      { property: "og:description", content: "See where the sharps sit on every live prediction market, next to the price." },
    ],
  }),
  component: Lobby,
});

const CATS = ["All", "Economy", "Crypto", "Climate", "Politics", "Tech"];
const SORTS = [
  { k: "gap", l: "Skill gap" },
  { k: "volume", l: "Volume" },
  { k: "closing", l: "Closing soonest" },
] as const;

function Lobby() {
  const markets = Route.useLoaderData();
  const top = featured(markets);
  const [cat, setCat] = useState("All");
  const [sort, setSort] = useState<(typeof SORTS)[number]["k"]>("gap");

  const others = useMemo(() => {
    const list = markets.filter((m) => m.id !== top.id && (cat === "All" || m.category === cat));
    return list.sort((a, b) =>
      sort === "gap"
        ? Math.abs(skillGap(b)) - Math.abs(skillGap(a))
        : sort === "volume"
          ? b.volume_usd - a.volume_usd
          : a.closes_at.localeCompare(b.closes_at),
    );
  }, [markets, top.id, cat, sort]);

  const pill = (on: boolean) =>
    cn(
      "rounded-full border px-3 py-1 text-sm transition-colors",
      on ? "border-gold bg-gold font-semibold text-primary-foreground" : "border-border text-text-2 hover:border-gold",
    );

  return (
    <div className="space-y-12">
      <section className="space-y-4">
        <p className="caption">
          Highest stakes tonight · {top.category} · Closes {fmtDate(top.closes_at)}
        </p>
        <h1 className="max-w-4xl text-4xl leading-tight md:text-6xl">{top.question}</h1>
        <Legend />
      </section>

      <PokerTable m={top} />
      <div className="flex justify-center">
        <Link to="/table/$id" params={{ id: top.id }} className={goldLinkClass}>See every hand at this table</Link>
      </div>

      <section className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <h2 className="text-3xl text-gold-light">Other tables</h2>
          <div className="flex flex-col gap-2 sm:items-end">
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
              {CATS.map((c) => (
                <button key={c} type="button" aria-pressed={cat === c} className={pill(cat === c)} onClick={() => setCat(c)}>
                  {c}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Sort tables">
              <span className="text-sm text-text-3">Sort:</span>
              {SORTS.map((s) => (
                <button key={s.k} type="button" aria-pressed={sort === s.k} className={pill(sort === s.k)} onClick={() => setSort(s.k)}>
                  {s.l}
                </button>
              ))}
            </div>
          </div>
        </div>
        {others.length === 0 ? (
          <p className="text-text-3">No other tables in this category tonight.</p>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {others.map((m) => {
              const g = skillGap(m);
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
                  <div className="space-y-2">
                    <p className="text-[11px] uppercase tracking-widest text-text-3">
                      {m.category} · {fmtDate(m.closes_at)}
                    </p>
                    <h3 className="font-sans text-base font-semibold text-foreground group-hover:text-gold-light">{m.question}</h3>
                    <p className="text-sm text-text-2">
                      House: YES {cents(m.yes_price)} · Sharps: {Math.round(skilledYesShare(m) * 100)}% on YES
                    </p>
                    <p className="text-sm text-gold-light">{verdict(g)}</p>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

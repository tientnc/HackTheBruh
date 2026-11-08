import { createFileRoute } from "@tanstack/react-router";
import { useMemo } from "react";
import {
  filterMarkets,
  type CallFilter,
  getMarkets,
  snapLabel,
  topDisagreements,
  type LobbySort,
  type Snap,
} from "@/lib/data";
import { useMode } from "@/hooks/use-mode";
import { LOBBY_PAGE, useLobbyState } from "@/hooks/use-lobby-state";
import { ModeBar } from "@/components/jett/ModeBar";
import { MarketCard } from "@/components/jett/MarketCard";
import { TiersBanner } from "@/components/jett/TiersBanner";
import { FollowTheMoney } from "@/components/jett/FollowTheMoney";
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
          "Every 2026 prediction market we track, with where the proven traders sat before it closed.",
      },
      { property: "og:title", content: "Lobby · Jett Showdown" },
      {
        property: "og:description",
        content:
          "Every 2026 prediction market we track, with where the proven traders sat before it closed.",
      },
    ],
  }),
  component: Lobby,
});

const SORTS: { k: LobbySort; l: string; showdownOnly?: boolean }[] = [
  { k: "hits", l: "Sharps' best calls", showdownOnly: true },
  { k: "gap", l: "Skill gap" },
  { k: "volume", l: "Volume" },
  { k: "closing", l: "Newest" },
];

const CALLS: { k: CallFilter; l: string }[] = [
  { k: "all", l: "All" },
  { k: "called", l: "Any call" },
  { k: "YES", l: "Sharps say YES" },
  { k: "NO", l: "Sharps say NO" },
  { k: "none", l: "No call" },
];

const pill = (on: boolean) =>
  cn(
    "min-h-9 rounded-full border px-3 py-1 text-sm transition-colors",
    on
      ? "border-gold bg-gold font-semibold text-primary-foreground"
      : "border-border text-text-2 hover:border-gold",
  );

function Lobby() {
  const markets = Route.useLoaderData();
  const { view, at, news } = useMode();
  const live = view === "live";
  const [state, update] = useLobbyState();

  const cats = useMemo(
    () => ["All", ...Array.from(new Set(markets.map((m) => m.category))).sort()],
    [markets],
  );
  const category = cats.includes(state.category) ? state.category : "All";
  // Live mode hides results, so it can't sort by them
  const sort: LobbySort = live && state.sort === "hits" ? "gap" : state.sort;
  const list = useMemo(
    () => filterMarkets(markets, { query: state.query, category, call: state.call, sort }),
    [markets, state.query, category, state.call, sort],
  );
  const disagreements = useMemo(() => topDisagreements(markets), [markets]);

  return (
    <div className="space-y-12">
      <section className="space-y-4">
        <ModeBar />
        {news && (
          <p className="text-sm text-text-3">
            Experimental news is on. Open a table to see archived headlines for its snapshot.
          </p>
        )}
        <p className="caption">
          {live ? "Live markets" : "Replay"} · frozen {snapLabel[at]} before close
        </p>
        <h1 className="text-5xl leading-tight md:text-6xl">The Lobby</h1>
        <p className="max-w-3xl text-text-2">
          {live
            ? `Every table is a real Polymarket market from 2026, shown as it stood ${snapLabel[at]} before it closed. Pick one to see where the proven traders sit and what they predict.`
            : `Every table is a real Polymarket market from 2026, frozen ${snapLabel[at]} before it closed. Pick one to see where the money sat, then the showdown.`}
        </p>
        <TiersBanner />
      </section>

      {!live && <FollowTheMoney markets={markets} at={at} />}

      <section aria-labelledby="all-tables" className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="all-tables" className="text-3xl text-gold-light">
              All tables
            </h2>
            <p className="text-sm text-text-3" aria-live="polite">
              {list.length === markets.length
                ? `${markets.length} markets`
                : `${list.length} of ${markets.length} markets`}
            </p>
          </div>
          <label className="flex w-full max-w-sm flex-col gap-1 text-sm text-text-2">
            Search markets
            <input
              type="search"
              value={state.query}
              onChange={(e) => update({ query: e.target.value, shown: LOBBY_PAGE })}
              placeholder="Fed, Gold, Apple, IPO…"
              className="min-h-11 rounded-full border border-border bg-panel px-4 text-foreground placeholder:text-text-3 focus:border-gold focus:outline-none"
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
            {cats.map((c) => (
              <button
                key={c}
                type="button"
                aria-pressed={category === c}
                className={pill(category === c)}
                onClick={() => update({ category: c, shown: LOBBY_PAGE })}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Filter by the sharps' call"
          >
            <span className="text-sm text-text-3">Sharps' call:</span>
            {CALLS.map((c) => (
              <button
                key={c.k}
                type="button"
                aria-pressed={state.call === c.k}
                className={pill(state.call === c.k)}
                onClick={() => update({ call: c.k, shown: LOBBY_PAGE })}
              >
                {c.l}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Sort tables">
            <span className="text-sm text-text-3">Sort:</span>
            {SORTS.filter((s) => !(live && s.showdownOnly)).map((s) => (
              <button
                key={s.k}
                type="button"
                aria-pressed={sort === s.k}
                className={pill(sort === s.k)}
                onClick={() => update({ sort: s.k, shown: LOBBY_PAGE })}
              >
                {s.l}
              </button>
            ))}
          </div>
        </div>

        {list.length === 0 ? (
          <p className="text-text-3">No tables match these filters.</p>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {list.slice(0, state.shown).map((m) => (
              <MarketCard key={m.id} m={m} view={view} />
            ))}
          </div>
        )}
        {list.length > state.shown && (
          <div className="flex justify-center">
            <button
              type="button"
              className="min-h-11 rounded-full border border-gold px-5 text-sm font-semibold text-gold-light hover:bg-gold hover:text-primary-foreground"
              onClick={() => update({ shown: state.shown + LOBBY_PAGE })}
            >
              Show more tables ({list.length - state.shown} left)
            </button>
          </div>
        )}
      </section>

      {disagreements.length > 0 && (
        <section aria-labelledby="disagreements" className="space-y-4">
          <div>
            <h2 id="disagreements" className="text-3xl text-gold-light">
              Biggest disagreements
            </h2>
            <p className="text-sm text-text-3">
              Where proven traders differ most from the market price.
            </p>
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            {disagreements.map((m) => (
              <MarketCard key={m.id} m={m} view={view} featured />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { ModeBar } from "@/components/jett/ModeBar";
import { GoldLink, Panel } from "@/components/jett/Shell";
import { TiersBanner } from "@/components/jett/TiersBanner";
import { useMode } from "@/hooks/use-mode";
import {
  cents,
  dataMeta,
  fmtUsd,
  getMarkets,
  sharpsBoard,
  snapLabel,
  type SharpRow,
  type Snap,
} from "@/lib/data";

export const Route = createFileRoute("/sharps")({
  loaderDeps: ({ search }) => ({ at: ((search as { at?: Snap }).at ?? "24h") as Snap }),
  loader: ({ deps }) => getMarkets(deps.at),
  head: () => ({
    meta: [
      { title: "The Sharps · Jett Showdown" },
      {
        name: "description",
        content:
          "The wallets with a proven record before 2026, and where they sat at the 2026 tables.",
      },
      { property: "og:title", content: "The Sharps · Jett Showdown" },
      {
        property: "og:description",
        content:
          "The wallets with a proven record before 2026, and where they sat at the 2026 tables.",
      },
    ],
  }),
  component: Sharps,
});

const pct = (x: number) => `${Math.round(x * 100)}%`;
const fullWallet = (w: string) => `${w.slice(0, 6)}…${w.slice(-4)}`;

function Stat({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <Panel className="space-y-2">
      <p className="text-sm text-text-3">{label}</p>
      <p className="font-display text-5xl text-foreground">{value}</p>
      <p className="text-sm text-text-2">{children}</p>
    </Panel>
  );
}

function Record({ r }: { r: SharpRow }) {
  if (!r.resolved || r.priceImplied === null) return <span className="text-text-3">—</span>;
  return (
    <span>
      <span className="font-semibold text-foreground">
        {r.won} of {r.resolved}
      </span>{" "}
      <span className="text-text-3">(price said {pct(r.priceImplied)})</span>
    </span>
  );
}

function Sharps() {
  const markets = Route.useLoaderData();
  const { view, at } = useMode();
  const showdown = view === "showdown";
  const board = sharpsBoard(markets);
  const seats = board.reduce((t, r) => t + r.hands.length, 0);
  const done = board.flatMap((r) => r.hands.filter((h) => h.outcome));
  const won = done.filter((h) => h.side === h.outcome).length;
  const implied = done.length ? done.reduce((t, h) => t + h.entry_price, 0) / done.length : null;

  return (
    <div className="space-y-12">
      <section className="space-y-4">
        <ModeBar />
        <p className="caption">Frozen {snapLabel[at]} before close</p>
        <h1 className="text-5xl leading-tight md:text-6xl">The Sharps</h1>
        <p className="max-w-3xl text-text-2">
          A sharp is a wallet that made more per dollar than almost everyone else on Polymarket
          markets that finished before 2026. Nothing from 2026 went into choosing them. Here is
          every sharp who sat at one of our 2026 tables, and the side they took.
        </p>
        <TiersBanner />
      </section>

      <section aria-label="Summary" className="grid gap-6 md:grid-cols-3">
        <Stat label="Sharps found before 2026" value={String(dataMeta.skilled_wallets ?? "—")}>
          {dataMeta.rated_wallets
            ? `Out of ${dataMeta.rated_wallets} wallets with enough history to rate.`
            : "Wallets with a proven record before 2026."}
        </Stat>
        <Stat label="At our 2026 tables" value={String(board.length)}>
          {seats} positions across {new Set(board.flatMap((r) => r.hands.map((h) => h.id))).size}{" "}
          tables, {snapLabel[at]} before close.
        </Stat>
        {showdown ? (
          <Stat label="Their side won" value={done.length ? pct(won / done.length) : "—"}>
            {done.length && implied !== null
              ? `${won} of ${done.length} positions. The prices they paid implied ${pct(implied)}.`
              : "No resolved positions yet."}
          </Stat>
        ) : (
          <Stat label="Results" value="Hidden">
            Live mode hides how things turned out. Switch to Showdown to see their record.
          </Stat>
        )}
      </section>

      <section aria-labelledby="board" className="space-y-4">
        <div>
          <h2 id="board" className="text-3xl text-gold-light">
            The table list
          </h2>
          <p className="text-sm text-text-3">
            Most active first. Open a row to see each position and jump to its table.
          </p>
        </div>
        {board.length === 0 ? (
          <Panel>
            <p className="text-text-2">No rated sharps sat at these tables.</p>
          </Panel>
        ) : (
          <ul className="space-y-3">
            {board.map((r, i) => (
              <li key={r.wallet}>
                <details className="group rounded-xl border border-border bg-panel open:border-gold">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-6 gap-y-2 p-4">
                    <span className="w-8 font-display text-2xl text-gold-light">{i + 1}</span>
                    <span className="min-w-40 font-mono text-foreground">
                      {fullWallet(r.wallet)}
                    </span>
                    <span className="text-text-2">
                      {r.tables} {r.tables === 1 ? "table" : "tables"} · {fmtUsd(r.staked)} staked
                    </span>
                    <span className="text-text-2">
                      {r.yes} YES · {r.no} NO
                    </span>
                    {showdown && (
                      <span className="text-sm text-text-2">
                        Won <Record r={r} />
                      </span>
                    )}
                    <span className="ml-auto text-sm text-text-3 group-open:hidden">
                      Show hands
                    </span>
                    <span className="ml-auto hidden text-sm text-text-3 group-open:inline">
                      Hide hands
                    </span>
                  </summary>
                  <div className="space-y-3 border-t border-border p-4">
                    <ul className="divide-y divide-border/60">
                      {r.hands.map((h) => (
                        <li
                          key={`${h.id}-${h.side}`}
                          className="flex flex-wrap items-center justify-between gap-3 py-2.5"
                        >
                          <Link
                            to="/table/$id"
                            params={{ id: h.id }}
                            search={{ view, at }}
                            className="text-foreground underline-offset-4 hover:text-gold-light hover:underline"
                          >
                            {h.question}
                          </Link>
                          <span className="text-sm text-text-2">
                            {h.side.toUpperCase()} at {cents(h.entry_price)} · {fmtUsd(h.stake_usd)}
                            {showdown && h.outcome && (
                              <span className="ml-2 font-semibold text-gold-light">
                                {h.side === h.outcome ? "Won" : "Lost"}
                              </span>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                    <a
                      href={`https://polymarket.com/profile/${r.wallet}`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-block text-sm text-text-2 underline underline-offset-4 hover:text-gold-light"
                    >
                      This wallet on Polymarket
                    </a>
                  </div>
                </details>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Panel className="space-y-2">
        <h2 className="text-xl text-gold-light">How to read this</h2>
        <p className="text-text-2">
          Winning alone isn’t the test: buying a 90¢ favourite wins most of the time. Compare how
          often their side won with what the price they paid implied. A wallet address is public on
          the blockchain, but we don’t know who is behind it.
        </p>
        <Link
          to="/how-to-play"
          className="inline-block text-sm text-text-2 underline underline-offset-4 hover:text-gold-light"
        >
          How to read a table
        </Link>
      </Panel>

      <div className="flex justify-center">
        <GoldLink to="/">Back to the Lobby</GoldLink>
      </div>
    </div>
  );
}

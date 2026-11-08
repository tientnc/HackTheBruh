import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { GapCard } from "@/components/jett/GapCard";
import { Chip } from "@/components/jett/Chips";
import { GoldLink, Panel } from "@/components/jett/Shell";
import { dataMeta, fmtDateYear, ratingSnapshot, type Tier } from "@/lib/data";

export const Route = createFileRoute("/house-rules")({
  head: () => ({
    meta: [
      { title: "House Rules · Jett Showdown" },
      { name: "description", content: "Exactly how Jett Showdown rates prediction-market wallets and calculates the skill gap." },
      { property: "og:title", content: "House Rules · Jett Showdown" },
      { property: "og:description", content: "Exactly how Jett Showdown rates prediction-market wallets and calculates the skill gap." },
    ],
  }),
  component: HouseRules,
});

function Rule({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="space-y-5">
      <p className="caption">Rule {n}</p>
      <h2 className="text-3xl md:text-4xl">{title}</h2>
      {children}
    </section>
  );
}

function Cream({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="playing-card p-5">
      <h3 className="mb-2 text-xl">{title}</h3>
      <div className="text-sm leading-relaxed">{children}</div>
    </div>
  );
}

const bets = [
  ["YES at 20¢", "Won", "+80"],
  ["YES at 60¢", "Lost", "−60"],
  ["NO at 35¢", "Won", "+65"],
  ["YES at 50¢", "Lost", "−50"],
];

const tiers: { t: Tier; name: string; desc: string }[] = [
  { t: "skilled", name: "Skilled", desc: "The wallet clears all four peer benchmarks and has enough history to rate." },
  { t: "unskilled", name: "Unskilled", desc: "The wallet has enough history to rate and falls short on one or more benchmarks." },
  { t: "new", name: "Unrated", desc: "The wallet has too few resolved events or lacks usable data for a peer comparison." },
];

function HouseRules() {
  return (
    <div className="space-y-20">
      <section className="max-w-3xl space-y-4">
        <p className="caption">How Jett Showdown works</p>
        <h1 className="text-5xl md:text-7xl">House Rules</h1>
        <p className="text-lg text-text-2">
          Prediction-market prices tell you what the crowd thinks. We show what the traders who are usually right
          think, and exactly how we decide who they are.
        </p>
      </section>

      <section className="space-y-8">
        <h2 className="text-3xl text-gold-light">The short version</h2>
        <div className="grid gap-8 md:grid-cols-3">
          {[
            ["A", "♠", "Read the hands", `We use trade histories and verified outcomes from ${ratingSnapshot.markets} resolved finance markets.`, -4],
            ["K", "♥", "Rate the wallets", "We compare four measures of historical performance against eligible finance peers.", 2],
            ["Q", "♣", "Show where they sit", "On each replay, we show skilled, unskilled and unrated positions on YES and NO next to the market price.", 4],
          ].map(([r, s, t, d, tilt]) => (
            <div key={r as string} className="flex gap-4">
              <div className="shrink-0"><GapCard rank={r as string} suit={s as "♠"} size="sm" tilt={tilt as number} /></div>
              <div>
                <h3 className="mb-1 text-xl">{t}</h3>
                <p className="text-sm text-text-2">{d}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <Rule n={1} title="How we measure buy-side edge">
        <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
          <div className="felt space-y-4 rounded-2xl p-6">
            <p className="text-text-2">
              A price is a probability. A YES share at 20¢ means the market gives it a 20% chance. A player has edge
              when the things they back happen more often than the prices they paid implied. Here is one player, four bets:
            </p>
            <table className="w-full text-left text-sm">
              <thead className="text-gold-light">
                <tr className="border-b border-border"><th className="py-2">Bet</th><th className="py-2">Result</th><th className="py-2 text-right">Edge (points)</th></tr>
              </thead>
              <tbody>
                {bets.map(([b, r, e]) => (
                  <tr key={b} className="border-b border-border/60"><td className="py-2">{b}</td><td className="py-2">{r}</td><td className="py-2 text-right font-semibold">{e}</td></tr>
                ))}
                <tr><td className="py-2 font-semibold text-gold-light" colSpan={2}>Average edge per bet</td><td className="py-2 text-right font-display text-xl text-gold-light">+8.8</td></tr>
              </tbody>
            </table>
            <p className="text-xs text-text-3">
              Buy-side edge is the payout per share minus the purchase price. We weight by shares
              and use markets where the wallet only bought.
            </p>
          </div>
          <div className="space-y-5">
            <Cream title="Why not just win rate?">
              Someone who only buys 95¢ favourites wins 95% of the time, but that is exactly what the price promised. Zero edge.
            </Cream>
            <Cream title="Why not just profit?">
              One lucky long shot can make a wallet look like a genius. Profit rewards size and luck; edge rewards being right more than the price expected, again and again.
            </Cream>
          </div>
        </div>
      </Rule>

      <Rule n={2} title="You have to earn a seat.">
        <div className="grid gap-5 md:grid-cols-3">
          {[
            ["14+", "resolved events", "A wallet needs at least 14 distinct resolved events and usable data for all four measures."],
            ["4", "peer benchmarks", "Skilled wallets beat the median of eligible finance peers on estimated profit, ROI, profitable-market rate, and buy-side edge. We exclude each wallet from its own benchmark."],
            ["0", "future results", `The rating snapshot uses outcomes available before ${fmtDateYear(ratingSnapshot.asOf)} UTC.`],
          ].map(([big, t, d]) => (
            <Panel key={t}>
              <p className="font-display text-4xl text-gold">{big}</p>
              <h3 className="mt-1 font-sans text-lg font-semibold">{t}</h3>
              <p className="mt-2 text-sm text-text-2">{d}</p>
            </Panel>
          ))}
        </div>
      </Rule>

      <Rule n={3} title="Every player gets a chip colour.">
        <div className="space-y-3">
          {tiers.map(({ t, name, desc }) => (
            <Panel key={t} className="flex items-center gap-5">
              <Chip tier={t} className="h-8 w-20 shrink-0" />
              <div>
                <h3 className="text-xl">{name}</h3>
                <p className="text-sm text-text-2">{desc}</p>
              </div>
            </Panel>
          ))}
        </div>
      </Rule>

      <Rule n={4} title="Reading the skill gap.">
        <div className="felt rounded-2xl p-6 text-center font-display text-xl text-gold-light md:text-2xl">
          Skill gap = % of skilled money on YES − YES price
        </div>
        <div className="grid gap-8 md:grid-cols-3">
          {[
            [24, "Skilled 78% vs 54¢", "Sharps are more confident in YES than the house."],
            [-16, "Skilled 15% vs 31¢", "Sharps are more confident in NO than the house."],
            [3, "Skilled 70% vs 67¢", "Sharps and the house broadly agree."],
          ].map(([g, a, b]) => (
            <div key={g as number} className="flex items-center gap-4">
              <div className="shrink-0"><GapCard gap={g as number} size="md" /></div>
              <div>
                <p className="font-semibold">{a}</p>
                <p className="text-sm text-text-2">{b}</p>
              </div>
            </div>
          ))}
        </div>
        <p className="text-text-3">A gap is a signal, not a prediction.</p>
      </Rule>

      <Rule n={5} title="We test it on hands already played.">
        <p className="max-w-3xl text-text-2">
          The Scoreboard replays {dataMeta.markets} resolved markets using the frozen wallet ratings
          and the trades available at each snapshot. It compares the sharps’ calls with the
          market favorite on the same tables.
        </p>
        <Link to="/scoreboard" className="inline-block text-gold-light underline underline-offset-4 hover:text-gold">
          See the full Scoreboard
        </Link>
      </Rule>

      <section className="space-y-5">
        <h2 className="text-3xl text-gold-light">What the house won't promise</h2>
        <ul className="grid gap-3 md:grid-cols-2">
          {[
            ["Information, not advice.", "We show where money sits. What you do with it is up to you."],
            ["Wallets aren't people.", "One person can run many wallets, and one wallet can be shared."],
            ["Past skill isn't future skill.", "A strong record can end at any time."],
            ["Suspicious isn't proof.", "We never accuse anyone or try to identify who is behind a wallet."],
            ["Signals fade.", "Once a gap is widely seen, the price may move to close it."],
            ["We can be wrong too.", "Our data and model have limits, and we will make mistakes."],
          ].map(([t, d]) => (
            <li key={t} className="rounded-lg border border-border bg-panel p-4">
              <span className="font-semibold text-foreground">{t}</span> <span className="text-text-2">{d}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-4">
        <h2 className="text-3xl text-gold-light">Where the cards come from</h2>
        <p className="max-w-3xl text-text-2">
          Trades and prices come from Polymarket’s public Data API. Wallet ratings and replay
          positions come from published snapshots.
        </p>
        <GoldLink to="/">Back to the Lobby</GoldLink>
      </section>
    </div>
  );
}

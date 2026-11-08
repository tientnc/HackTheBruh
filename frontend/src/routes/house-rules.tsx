import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { GapCard } from "@/components/jett/GapCard";
import { Chip } from "@/components/jett/Chips";
import { GoldLink, Panel } from "@/components/jett/Shell";
import type { Tier } from "@/lib/data";

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
  { t: "skilled", name: "Skilled", desc: "Top 10% of rated wallets by edge, with 30+ resolved bets, and the edge passes the statistical test." },
  { t: "unskilled", name: "Unskilled", desc: "Rated wallets with 30+ resolved bets that are not in the top 10% by edge." },
  { t: "new", name: "New", desc: "Fewer than 30 resolved bets. Shown separately because we cannot rate them yet. We never label anyone an insider." },
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
            ["A", "♠", "Read every hand", "We pull every resolved trade from every wallet on Polymarket: what they bought, at what price, and how it turned out.", -4],
            ["K", "♥", "Rate every player", "Each wallet gets a score for how often it beats the price it paid. Proven players become Skilled.", 2],
            ["Q", "♣", "Show where they sit", "On every live market, we show how much skilled, unskilled and new money is on YES and NO, next to the price.", 4],
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

      <Rule n={1} title="We rate players on edge, not wins.">
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
              Edge on a bet = result (1 if it won, 0 if not) minus the price paid. In the real model, bigger stakes count for more.
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
            ["30+", "resolved bets", "A wallet needs at least 30 finished bets before we rate it."],
            ["Real", "It has to be real", "The edge must pass a statistical test, so a short lucky streak is not enough."],
            ["0", "look-ahead", "Only markets that have already finished count towards a rating."],
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
          To check the model, we go back to markets that have already resolved and rebuild each one as it looked at the
          time, using only trades and ratings that existed on that date. Nothing from the future leaks in. Then we compare
          what skilled money said with what actually happened.
        </p>
        <div className="grid gap-5 md:grid-cols-3">
          <Cream title="Resolved markets tested"><p className="font-display text-3xl">[YOUR NUMBER]</p></Cream>
          <Cream title="Skilled money accuracy vs price"><p className="font-display text-3xl">[YOUR RESULT]</p></Cream>
          <Cream title="When the gap was 15+ points"><p className="font-display text-3xl">[YOUR RESULT]</p></Cream>
        </div>
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
          All trades and market prices come from Polymarket's public Data API. Wallet ratings are refreshed [HOW OFTEN];
          live market positions and prices are refreshed [HOW OFTEN].
        </p>
        <GoldLink to="/">Back to the Lobby</GoldLink>
      </section>
    </div>
  );
}

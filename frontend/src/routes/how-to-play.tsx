import { createFileRoute } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { readGap } from "@/lib/data";
import { GapCalculator } from "@/components/jett/GapCalculator";
import { GapCard } from "@/components/jett/GapCard";
import { GoldLink, Panel } from "@/components/jett/Shell";

export const Route = createFileRoute("/how-to-play")({
  head: () => ({
    meta: [
      { title: "How to Play · Jett Showdown" },
      {
        name: "description",
        content:
          "How prediction markets work, what the skill gap means, and how to read every kind of table, in plain language.",
      },
      { property: "og:title", content: "How to Play · Jett Showdown" },
      {
        property: "og:description",
        content:
          "How prediction markets work, what the skill gap means, and how to read every kind of table, in plain language.",
      },
    ],
  }),
  component: HowToPlay,
});

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="space-y-5" aria-labelledby={`step-${n}`}>
      <p className="caption">Step {n}</p>
      <h2 id={`step-${n}`} className="text-3xl md:text-4xl">
        {title}
      </h2>
      {children}
    </section>
  );
}

const basics = [
  {
    rank: "A",
    suit: "♠" as const,
    title: "Every market is a yes/no question",
    body: "You can buy YES shares or NO shares. When the market ends, every winning share pays $1 and every losing share pays nothing.",
  },
  {
    rank: "K",
    suit: "♥" as const,
    title: "The price is the crowd's guess",
    body: "A YES share at 54¢ means traders, all together, give YES about a 54% chance. YES and NO prices add up to about $1.",
  },
  {
    rank: "Q",
    suit: "♣" as const,
    title: "You can sell any time",
    body: "Prices move as news arrives. You can hold to the end, or sell early to lock in a profit or cut a loss, just like a stock.",
  },
];

// Every kind of table, with the numbers that produce it.
const scenarios: { label: string; sharp: number | null; price: number; note?: string }[] = [
  { label: "Sharps keener on YES than the crowd", sharp: 78, price: 54 },
  { label: "Sharps keener on NO than the crowd", sharp: 15, price: 31 },
  { label: "Sharps and crowd agree", sharp: 70, price: 67 },
  {
    label: "The trap: sharps on YES, but YES is expensive",
    sharp: 78,
    price: 90,
    note: "Most of the skilled money is on YES, so it's tempting to buy YES. But the crowd is even more confident (90%) than the sharps (78%). Paying 90¢ for YES means paying more than the sharps think it's worth. What matters is the gap, not the side.",
  },
  { label: "Not enough skilled money", sharp: null, price: 40 },
];

function HowToPlay() {
  return (
    <div className="space-y-20">
      <section className="space-y-4">
        <p className="caption">How to play</p>
        <h1 className="text-5xl leading-tight md:text-6xl">How to read a table</h1>
        <p className="max-w-3xl text-lg text-text-2">
          Jett Showdown never tells you what to bet. It shows you where traders with a proven record
          sit compared with the price, so you can make up your own mind. Here's everything you need,
          in about five minutes.
        </p>
      </section>

      <Step n={1} title="How the market works">
        <div className="grid gap-6 md:grid-cols-3">
          {basics.map((b) => (
            <Panel key={b.title} className="space-y-4">
              <GapCard rank={b.rank} suit={b.suit} size="sm" tilt={-4} />
              <h3 className="text-xl text-gold-light">{b.title}</h3>
              <p className="text-text-2">{b.body}</p>
            </Panel>
          ))}
        </div>
        <Panel className="space-y-3">
          <h3 className="text-xl text-gold-light">An example</h3>
          <ol className="list-decimal space-y-2 pl-5 text-text-2">
            <li>You buy 100 YES shares at 30¢. That costs $30.</li>
            <li>
              Good news comes out and YES rises to 70¢. You could sell now for $70, a $40 profit,
              whatever happens next.
            </li>
            <li>Or you hold to the end: if YES wins you get $100; if NO wins you get $0.</li>
          </ol>
        </Panel>
      </Step>

      <Step n={2} title="The one number that matters: the skill gap">
        <p className="max-w-3xl text-text-2">
          We rate every wallet on its track record. On each table we add up where the{" "}
          <strong className="text-foreground">skilled</strong> wallets have their money, and compare
          it with the price.
        </p>
        <div className="rounded-xl border-2 border-gold bg-panel px-6 py-5 text-center text-xl md:text-2xl">
          Skill gap = % of skilled money on YES − YES price
        </div>
        <div className="grid items-center gap-6 md:grid-cols-[auto_1fr]">
          <GapCard gap={24} size="md" tilt={-4} />
          <p className="text-text-2">
            Skilled money is 78% on YES and YES costs 54¢: 78 − 54 ={" "}
            <strong className="text-foreground">+24</strong>. The question is never just{" "}
            <em>which side</em> the sharps are on. It's whether they're{" "}
            <strong className="text-foreground">more confident than the price</strong>. That's where
            a bargain might be.
          </p>
        </div>
      </Step>

      <Step n={3} title="Every kind of table, in plain language">
        <div id="scenarios" className="space-y-4 scroll-mt-24">
          {scenarios.map((s) => {
            const r = readGap(s.sharp === null ? null : s.sharp / 100, s.price / 100);
            const gap = s.sharp === null ? null : s.sharp - s.price;
            return (
              <Panel key={s.label} className="grid gap-6 md:grid-cols-[auto_1fr]">
                <div className="flex justify-center md:block">
                  <GapCard gap={gap} size="md" tilt={-4} />
                </div>
                <div className="space-y-3">
                  <p className="caption">{s.label}</p>
                  <h3 className="text-2xl text-gold-light">{r.headline}</h3>
                  <p className="text-sm text-text-3">
                    {s.sharp === null
                      ? `YES price ${s.price}¢ · too little skilled money to compare`
                      : `Skilled money ${s.sharp}% on YES · YES price ${s.price}¢`}
                  </p>
                  <p className="text-text-2">{s.note ?? r.means}</p>
                  <p className="text-text-2">
                    <strong className="text-foreground">Someone who trusts the sharps might</strong>{" "}
                    {s.note
                      ? "avoid paying 90¢ for YES. If anything, NO is the better-value side."
                      : r.might}
                  </p>
                </div>
              </Panel>
            );
          })}
          <Panel className="space-y-2">
            <h3 className="text-xl text-gold-light">If you already own shares</h3>
            <p className="text-text-2">
              Selling only matters if you already hold a side. If the gap turns strongly against the
              side you own, the proven traders are betting the other way. That's a reason to look
              again, and some holders would sell.
            </p>
          </Panel>
        </div>
      </Step>

      <Step n={4} title="Try it yourself">
        <Panel>
          <GapCalculator />
        </Panel>
      </Step>

      <Step n={5} title="Before trusting any signal">
        <div className="grid gap-6 md:grid-cols-3">
          <Panel className="space-y-2">
            <h3 className="text-xl text-gold-light">Check the track record</h3>
            <p className="text-text-2">
              Does following the sharps actually beat the price? The Scoreboard shows how often they
              were right on past markets. If they weren't, trust them less.
            </p>
          </Panel>
          <Panel className="space-y-2">
            <h3 className="text-xl text-gold-light">Check the strength</h3>
            <p className="text-text-2">
              Lots of skilled wallets with real money is a stronger signal than one big wallet. Each
              table shows how many skilled wallets are on each side.
            </p>
          </Panel>
          <Panel className="space-y-2">
            <h3 className="text-xl text-gold-light">Only risk what you can lose</h3>
            <p className="text-text-2">
              Shares can go to zero. Skilled traders are wrong too, and past skill doesn't guarantee
              future results.
            </p>
          </Panel>
        </div>
      </Step>

      <Step n={6} title="Live and Showdown modes">
        <div className="grid gap-6 md:grid-cols-2">
          <Panel className="space-y-2">
            <h3 className="text-xl text-gold-light">Live</h3>
            <p className="text-text-2">
              What a user would see on a market that hasn't ended: the money, the price and the
              sharps' prediction. The result stays hidden.
            </p>
          </Panel>
          <Panel className="space-y-2">
            <h3 className="text-xl text-gold-light">Showdown</h3>
            <p className="text-text-2">
              Our proof of concept. These are real markets that have already ended, so we can reveal
              the result and check whether the sharps were right.
            </p>
          </Panel>
        </div>
      </Step>

      <Panel className="flex flex-col items-center gap-4 py-10 text-center">
        <p className="max-w-xl text-text-2">
          Jett Showdown shows information, not advice. What you do with it is up to you.
        </p>
        <GoldLink to="/">Go to the Lobby</GoldLink>
      </Panel>
    </div>
  );
}

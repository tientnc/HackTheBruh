import { createFileRoute, notFound } from "@tanstack/react-router";
import {
  CartesianGrid,
  Legend as RLegend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  cents,
  chipUnit,
  fmtDate,
  fmtDateYear,
  fmtUsd,
  getMarket,
  shortWallet,
  skillGap,
  verdict,
} from "@/lib/data";
import { PokerTable } from "@/components/jett/PokerTable";
import { TiersBanner } from "@/components/jett/TiersBanner";
import { Chip, Legend, tierLabel } from "@/components/jett/Chips";
import { GoldLink, Panel } from "@/components/jett/Shell";

export const Route = createFileRoute("/table/$id")({
  loader: async ({ params }) => {
    const m = await getMarket(params.id);
    if (!m) throw notFound();
    return m;
  },
  head: ({ loaderData }) => {
    const t = loaderData
      ? `${loaderData.question} · Jett Showdown`
      : "Table unavailable · Jett Showdown";
    const d = loaderData
      ? `${verdict(skillGap(loaderData))}. See every hand at this table.`
      : "This table could not be found.";
    return {
      meta: [
        { title: t },
        { name: "description", content: d },
        { property: "og:title", content: t },
        { property: "og:description", content: d },
        ...(loaderData ? [] : [{ name: "robots", content: "noindex" }]),
      ],
    };
  },
  notFoundComponent: () => (
    <div className="space-y-6 py-16 text-center">
      <h1 className="text-4xl">This table has closed</h1>
      <GoldLink to="/">Back to the Lobby</GoldLink>
    </div>
  ),
  component: TablePage,
});

function TablePage() {
  const m = Route.useLoaderData();
  const data = m.skilled_share_history.map((h) => ({
    date: fmtDate(h.date),
    skilled: h.skilled_yes_share === null ? null : Math.round(h.skilled_yes_share * 100),
    price: Math.round(h.yes_price * 100),
  }));
  const big = m.top_positions.slice(0, 6);
  const fresh = m.top_positions.filter((p) => p.tier === "new").slice(0, 5);

  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <p className="caption">
          Replay · {m.category} · Frozen 24h before close · {fmtDateYear(m.closes_at)} ·{" "}
          {fmtUsd(m.volume_usd)} traded by then
        </p>
        <h1 className="max-w-4xl text-4xl leading-tight md:text-5xl">{m.question}</h1>
        <p className="text-gold-light">{verdict(skillGap(m))}</p>
        <TiersBanner />
        <Legend unit={chipUnit(m)} />
        {m.source_url && (
          <a
            href={m.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-block text-sm text-text-2 underline underline-offset-4 hover:text-gold-light"
          >
            View this market on Polymarket
          </a>
        )}
      </section>
      <PokerTable m={m} />

      <Panel>
        <h2 className="mb-4 text-2xl text-gold-light">How the hand played out</h2>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ left: -10, right: 10 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="var(--text-3)" fontSize={12} />
              <YAxis domain={[0, 100]} stroke="var(--text-3)" fontSize={12} unit="%" />
              <Tooltip
                contentStyle={{
                  background: "var(--panel)",
                  border: "1px solid var(--border)",
                  color: "var(--foreground)",
                }}
              />
              <RLegend />
              <Line
                type="monotone"
                dataKey="skilled"
                name="Skilled share on YES (%)"
                stroke="var(--gold)"
                strokeWidth={3}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="price"
                name="YES price (¢)"
                stroke="var(--card-paper)"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <Panel>
          <h2 className="mb-4 text-2xl text-gold-light">Biggest seats at the table</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-text-3">
                <tr className="border-b border-border">
                  <th className="py-2 font-medium">Wallet</th>
                  <th className="py-2 font-medium">Tier</th>
                  <th className="py-2 font-medium">Side</th>
                  <th className="py-2 text-right font-medium">Stake</th>
                  <th className="py-2 text-right font-medium">Entry</th>
                </tr>
              </thead>
              <tbody>
                {big.map((p) => (
                  <tr
                    key={`${p.wallet}-${p.side}`}
                    className="border-b border-border/60 text-text-2"
                  >
                    <td className="py-2.5 font-mono">{shortWallet(p.wallet)}</td>
                    <td className="py-2.5">
                      <span className="flex items-center gap-2">
                        <Chip tier={p.tier} className="w-7" />
                        {tierLabel[p.tier]}
                      </span>
                    </td>
                    <td className="py-2.5 font-semibold text-foreground">{p.side.toUpperCase()}</td>
                    <td className="py-2.5 text-right">{fmtUsd(p.stake_usd)}</td>
                    <td className="py-2.5 text-right">{cents(p.entry_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel>
          <h2 className="mb-1 text-2xl text-gold-light">Unrated at the table</h2>
          <p className="mb-4 text-sm text-text-3">
            Large positions from wallets we have not rated.
          </p>
          {fresh.length === 0 ? (
            <p className="text-sm text-text-3">No large unrated positions on this table.</p>
          ) : (
            <ul className="space-y-3">
              {fresh.map((p) => (
                <li
                  key={`${p.wallet}-${p.side}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 text-sm"
                >
                  <span className="flex items-center gap-2">
                    <Chip tier="new" className="w-7" />
                    <span>
                      <span className="block font-mono text-foreground">
                        {shortWallet(p.wallet)}
                      </span>
                      <span className="text-xs text-text-3">Not rated</span>
                    </span>
                  </span>
                  <span className="text-right text-text-2">
                    {fmtUsd(p.stake_usd)} on {p.side.toUpperCase()}
                    <span className="block text-xs text-text-3">at {cents(p.entry_price)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}

import { createFileRoute } from "@tanstack/react-router";
import { GapCard } from "@/components/jett/GapCard";
import { GoldLink, Panel } from "@/components/jett/Shell";
import { fmtDate, getResearchMarkets } from "@/lib/data";

export const Route = createFileRoute("/scoreboard")({
  loader: () => getResearchMarkets(),
  head: () => ({
    meta: [
      { title: "Scoreboard · Jett Showdown" },
      { name: "description", content: "Outcomes from resolved markets in the historical research dataset." },
      { property: "og:title", content: "Scoreboard · Jett Showdown" },
      { property: "og:description", content: "Outcomes from resolved markets in the historical research dataset." },
    ],
  }),
  component: Scoreboard,
});

function Scoreboard() {
  const result = Route.useLoaderData();

  return (
    <div className="space-y-6">
      <Panel className="flex flex-col items-center gap-6 py-16 text-center">
        <GapCard rank="K" suit="♥" size="md" tilt={5} />
        <p className="caption">Historical research</p>
        <h1 className="text-5xl">Scoreboard</h1>
        <p className="max-w-md text-text-2">Outcomes from resolved markets in the research dataset.</p>
        {result.status === "connected" && (
          <p className="text-sm text-text-2">
            Supabase · Read only
            {result.markets.length === 0 && " · No published research markets yet"}
          </p>
        )}
        {result.status === "unconfigured" && (
          <p className="text-sm text-text-2">Supabase is not configured for this deployment.</p>
        )}
        {result.status === "unavailable" && (
          <p className="text-sm text-text-2">Supabase is temporarily unavailable.</p>
        )}
        <GoldLink to="/">Back to the Lobby</GoldLink>
      </Panel>
      {result.status === "connected" && result.markets.length > 0 && (
        <Panel>
          <h2 className="mb-4 text-2xl text-gold-light">Recently resolved markets</h2>
          <ul className="divide-y divide-border">
            {result.markets.map((market) => (
              <li key={`${market.dataset_key}:${market.market_id}`} className="flex flex-wrap justify-between gap-2 py-3">
                <span>{market.question}</span>
                <span className="text-text-2">
                  {market.yes_outcome === 1 ? "YES" : "NO"} · {fmtDate(new Date(market.label_available_at * 1000).toISOString())}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

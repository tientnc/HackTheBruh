import { createFileRoute } from "@tanstack/react-router";
import { GapCard } from "@/components/jett/GapCard";
import { GoldLink, Panel } from "@/components/jett/Shell";

export const Route = createFileRoute("/sharps")({
  head: () => ({
    meta: [
      { title: "The Sharps · Jett Showdown" },
      { name: "description", content: "The wallets with the strongest proven edge on prediction markets." },
      { property: "og:title", content: "The Sharps · Jett Showdown" },
      { property: "og:description", content: "The wallets with the strongest proven edge on prediction markets." },
    ],
  }),
  component: () => (
    <Panel className="flex flex-col items-center gap-6 py-16 text-center">
      <GapCard rank="A" suit="♠" size="md" />
      <p className="caption">Coming soon</p>
      <h1 className="text-5xl">The Sharps</h1>
      <p className="max-w-md text-text-2">The players with the strongest proven edge will take their seats here soon.</p>
      <GoldLink to="/">Back to the Lobby</GoldLink>
    </Panel>
  ),
});

import { createFileRoute } from "@tanstack/react-router";
import { GapCard } from "@/components/jett/GapCard";
import { GoldLink, Panel } from "@/components/jett/Shell";

export const Route = createFileRoute("/scoreboard")({
  head: () => ({
    meta: [
      { title: "Scoreboard · Jett Showdown" },
      { name: "description", content: "How the skill gap has performed on markets that have already resolved." },
      { property: "og:title", content: "Scoreboard · Jett Showdown" },
      { property: "og:description", content: "How the skill gap has performed on markets that have already resolved." },
    ],
  }),
  component: () => (
    <Panel className="flex flex-col items-center gap-6 py-16 text-center">
      <GapCard rank="K" suit="♥" size="md" tilt={5} />
      <p className="caption">Coming soon</p>
      <h1 className="text-5xl">Scoreboard</h1>
      <p className="max-w-md text-text-2">Results from hands already played will be posted here soon.</p>
      <GoldLink to="/">Back to the Lobby</GoldLink>
    </Panel>
  ),
});

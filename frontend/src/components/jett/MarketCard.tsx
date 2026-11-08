import { Link } from "@tanstack/react-router";
import { rememberLobbyScroll } from "@/hooks/use-lobby-state";
import {
  callResult,
  cents,
  fmtDateYear,
  predictionText,
  skillGap,
  skilledYesShare,
  verdict,
  type Market,
  type View,
} from "@/lib/data";
import { cn } from "@/lib/utils";
import { GapCard } from "./GapCard";
import { Sparkline } from "./Sparkline";

function resultText(m: Market): string {
  if (!m.outcome) return "";
  const r = callResult(m);
  const tail = r === "hit" ? "Sharps called it" : r === "miss" ? "Sharps missed" : "No sharp call";
  return `Result: ${m.outcome.toUpperCase()} · ${tail}`;
}

/** One market in the Lobby. `featured` is the larger version used for Biggest disagreements. */
export function MarketCard({
  m,
  view,
  featured = false,
}: {
  m: Market;
  view: View;
  featured?: boolean;
}) {
  const live = view === "live";
  const g = skillGap(m);
  const share = skilledYesShare(m);
  return (
    <Link
      to="/table/$id"
      params={{ id: m.id }}
      onClick={rememberLobbyScroll}
      className={cn(
        "group flex gap-4 rounded-xl border bg-panel p-5 transition-colors hover:border-gold",
        featured ? "border-gold/60" : "border-border",
      )}
    >
      <div className="shrink-0 pt-1">
        <GapCard gap={g} size={featured ? "md" : "sm"} tilt={-4} />
      </div>
      <div className="min-w-0 space-y-2">
        <p className="text-[11px] uppercase tracking-widest text-text-3">
          {m.category} · {live ? "Closes " : ""}
          {fmtDateYear(m.closes_at)}
        </p>
        <h3
          className={cn(
            "font-sans font-semibold text-foreground group-hover:text-gold-light",
            featured ? "text-lg" : "text-base",
          )}
        >
          {m.question}
        </h3>
        <p className="text-sm text-text-2">
          House: YES {cents(m.yes_price)} ·{" "}
          {share === null ? "Sharps: no rated money" : `Sharps: ${Math.round(share * 100)}% on YES`}
        </p>
        {m.spark && <Sparkline points={m.spark} />}
        <p className="text-sm text-gold-light">{verdict(g)}</p>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-2">
          {live ? `Prediction: ${predictionText(m)}` : resultText(m)}
        </p>
      </div>
    </Link>
  );
}

import { Link } from "@tanstack/react-router";
import { cents, followTheMoney, fmtCentsPerDollar, type Market, type Snap } from "@/lib/data";

/** The money test: $1 with every sharp call vs $1 on the crowd's favourite, held to the result. */
export function FollowTheMoney({
  markets,
  at,
  compact = false,
}: {
  markets: Market[];
  at: Snap;
  compact?: boolean;
}) {
  const f = followTheMoney(markets);
  if (!f.sharps.bets || f.sharps.perDollar === null) return null;
  return (
    <section
      aria-labelledby="follow-money"
      className="space-y-5 rounded-xl border border-gold bg-panel p-6"
    >
      <div>
        <p className="caption">Follow the money</p>
        <h2 id="follow-money" className="text-3xl text-gold-light md:text-4xl">
          {f.crowd.perDollar !== null && f.crowd.perDollar < 0 && f.sharps.perDollar > 0
            ? "Following the crowd lost money. Following the sharps made it."
            : "Following the sharps vs following the crowd"}
        </h2>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="space-y-1 rounded-lg bg-card-paper p-5 text-card-ink">
          <p className="text-sm font-semibold">$1 on every sharp call</p>
          <p className="font-display text-5xl">{fmtCentsPerDollar(f.sharps.perDollar)}</p>
          <p className="text-sm">per dollar, across {f.sharps.bets} bets</p>
        </div>
        <div className="space-y-1 rounded-lg border border-border p-5">
          <p className="text-sm font-semibold text-text-2">$1 on the crowd’s favourite</p>
          <p className="font-display text-5xl text-foreground">
            {fmtCentsPerDollar(f.crowd.perDollar)}
          </p>
          <p className="text-sm text-text-2">per dollar, across {f.crowd.bets} bets</p>
        </div>
        {f.best && (
          <Link
            to="/table/$id"
            params={{ id: f.best.market.id }}
            search={{ view: "showdown", at }}
            className="space-y-1 rounded-lg border border-border p-5 transition-colors hover:border-gold"
          >
            <p className="text-sm font-semibold text-text-2">Best hand</p>
            <p className="font-display text-5xl text-gold-light">{cents(f.best.price)}</p>
            <p className="text-sm text-text-2">
              The crowd priced {f.best.side === "yes" ? "NO" : "YES"} at {cents(1 - f.best.price)}.
              The sharps backed {f.best.side.toUpperCase()} at {cents(f.best.price)} on “
              {f.best.market.question}”, and {f.best.side.toUpperCase()} won.
            </p>
          </Link>
        )}
      </div>
      {!compact && (
        <p className="text-sm text-text-3">
          $1 at the frozen price, held to the result; tables priced under 0.5¢ or over 99.5¢ left
          out. Small sample: one longshot can move these numbers a lot.
        </p>
      )}
    </section>
  );
}

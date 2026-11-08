import { tiersFake, tiersPending } from "@/lib/data";

export function TiersBanner() {
  if (!tiersPending && !tiersFake) return null;
  return (
    <p
      role="status"
      className="rounded-xl border border-gold/60 bg-panel px-4 py-3 text-sm text-text-2"
    >
      {tiersPending ? (
        <>
          <strong className="text-gold-light">Wallet ratings are on their way.</strong> Until they
          land, every wallet shows as unrated, so the tables have no skill gap yet. Prices, money
          and results are real.
        </>
      ) : (
        <>
          <strong className="text-gold-light">Preview only:</strong> the wallet tiers on these
          tables are random placeholders, not real ratings. Prices, money and results are real.
        </>
      )}
    </p>
  );
}

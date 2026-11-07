import { createServerFn } from "@tanstack/react-start";
import raw from "@/data/markets.json";
import rawMeta from "@/data/meta.json";

// "new" holds wallets with no rating (not in the tiers file). The UI labels it "Unrated".
export type Tier = "skilled" | "unskilled" | "new";
export type Side = {
  skilled_usd: number;
  unskilled_usd: number;
  new_usd: number;
  skilled_wallets: number;
  unskilled_wallets: number;
  new_wallets: number;
};
export type Call = "YES" | "NO" | "INSUFFICIENT";
export type Market = {
  id: string;
  question: string;
  category: string;
  closes_at: string;
  yes_price: number;
  volume_usd: number;
  yes: Side;
  no: Side;
  skilled_share_history: { date: string; skilled_yes_share: number | null; yes_price: number }[];
  top_positions: {
    wallet: string;
    tier: Tier;
    side: "yes" | "no";
    stake_usd: number;
    entry_price: number;
  }[];
  // Replays of resolved markets (built by polyresearch/backtest/lobby.py)
  snapshot_at?: string;
  resolved_at?: string;
  outcome?: "yes" | "no";
  call?: Call;
  skilled_share?: number | null;
  source_url?: string | null;
};
export type DataMeta = {
  snapshot: string;
  tiers_source: string; // "none" = no ratings yet, "fake" = random preview tiers, else the tiers file name
  dataset: string;
  markets: number;
  skipped_unusable: number;
  generated_at: string;
};

// Snapshots of resolved 2026 markets, frozen 24 hours before each one closed.
export async function getMarkets(): Promise<Market[]> {
  return raw as Market[];
}
export async function getMarket(id: string): Promise<Market | undefined> {
  return (await getMarkets()).find((m) => m.id === id);
}
export const dataMeta = rawMeta as DataMeta;
export const tiersPending = dataMeta.tiers_source === "none";
export const tiersFake = dataMeta.tiers_source === "fake";

type ResearchMarket = {
  dataset_key: string;
  market_id: string;
  question: string;
  label_available_at: number;
  yes_outcome: 0 | 1;
};

type ResearchMarketRead =
  { status: "connected"; markets: ResearchMarket[] } | { status: "unconfigured" | "unavailable" };

export const getResearchMarkets = createServerFn({ method: "GET" }).handler(
  async (): Promise<ResearchMarketRead> => {
    const { SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } = process.env;
    if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) return { status: "unconfigured" };

    try {
      const url = new URL("/rest/v1/research_markets", SUPABASE_URL);
      url.search = new URLSearchParams({
        select: "dataset_key,market_id,question,label_available_at,yes_outcome",
        order: "label_available_at.desc,dataset_key,market_id",
        limit: "20",
      }).toString();
      const response = await fetch(url, {
        headers: { apikey: SUPABASE_PUBLISHABLE_KEY },
        signal: AbortSignal.timeout(5000),
      });
      if (response.ok) return { status: "connected", markets: await response.json() };
    } catch {
      return { status: "unavailable" };
    }
    return { status: "unavailable" };
  },
);

/** Share of skilled money on YES, or null when no skilled money is at the table. */
export function skilledYesShare(m: Pick<Market, "yes" | "no">): number | null {
  const total = m.yes.skilled_usd + m.no.skilled_usd;
  return total <= 0 ? null : m.yes.skilled_usd / total;
}
/** Skilled share on YES (%) minus the YES price (¢), or null with no skilled money. */
export function skillGap(m: Pick<Market, "yes" | "no" | "yes_price">): number | null {
  const share = skilledYesShare(m);
  return share === null ? null : Math.round(share * 100 - m.yes_price * 100);
}
export function verdict(gap: number | null): string {
  if (gap === null)
    return tiersPending ? "Wallet ratings pending" : "No rated sharps at this table";
  if (Math.abs(gap) <= 5) return "Sharps and the house agree";
  return gap > 0
    ? "Sharps are more confident in YES than the house"
    : "Sharps are more confident in NO than the house";
}
export function suitFor(gap: number | null): "♠" | "♣" | "♥" {
  if (gap === null || Math.abs(gap) <= 5) return "♥";
  return gap > 0 ? "♠" : "♣";
}
export const fmtGap = (gap: number | null) =>
  gap === null ? "?" : gap > 0 ? `+${gap}` : gap < 0 ? `−${-gap}` : "0";

/** Did the sharps' call (recommend.py's rule) match the outcome? */
export function callResult(m: Market): "hit" | "miss" | "none" {
  if (!m.outcome || !m.call || m.call === "INSUFFICIENT") return "none";
  return m.call.toLowerCase() === m.outcome ? "hit" : "miss";
}

/** Dollars per chip for one table: the biggest stack gets about 10 chips, rounded to 1/2/5 × 10^k. */
export function chipUnit(m: Pick<Market, "yes" | "no">): number {
  const biggest = Math.max(
    ...(["yes", "no"] as const).flatMap((s) => [
      m[s].skilled_usd,
      m[s].unskilled_usd,
      m[s].new_usd,
    ]),
  );
  if (biggest <= 0) return 1;
  const target = biggest / 10;
  const pow = 10 ** Math.floor(Math.log10(target));
  const step = [1, 2, 5, 10].find((k) => k * pow >= target) ?? 10;
  return step * pow;
}
export function chipCount(usd: number, unit = 40000): number {
  if (usd < 1) return 0;
  return Math.min(12, Math.max(1, Math.round(usd / unit)));
}

/** Featured table: the biggest skill gap among tables the sharps made a call on, then any gap, then the busiest contested market. */
export function featured(markets: Market[]): Market {
  const abs = (m: Market) => Math.abs(skillGap(m) ?? -1);
  const called = markets.filter((m) => m.call && m.call !== "INSUFFICIENT");
  const pool = called.length ? called : markets.filter((m) => skillGap(m) !== null);
  if (pool.length) return [...pool].sort((a, b) => abs(b) - abs(a))[0]!;
  // No ratings yet: show the busiest market that was still genuinely in doubt.
  const contested = markets.filter((m) => m.yes_price >= 0.15 && m.yes_price <= 0.85);
  return [...(contested.length ? contested : markets)].sort(
    (a, b) => b.volume_usd - a.volume_usd,
  )[0]!;
}
export const sideTotal = (s: Side) => s.skilled_usd + s.unskilled_usd + s.new_usd;
export const fmtUsd = (n: number) =>
  n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(2)}M`
    : n >= 1000
      ? `$${Math.round(n / 1000)}k`
      : `$${Math.round(n)}`;
export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
export const fmtDateYear = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
export const shortWallet = (w: string) => `${w.slice(0, 4)}…${w.slice(-2)}`;
export const cents = (p: number) => `${Math.round(p * 100)}¢`;

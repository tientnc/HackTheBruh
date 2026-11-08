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
  /** [unix seconds, YES price] up to the snapshot, for the small Lobby chart */
  spark?: [number, number][];
};
export type DataMeta = {
  snapshots: Record<Snap, number>;
  tiers_source: string; // "none" = no ratings yet, "fake" = random preview tiers, else the tiers file name
  dataset: string;
  markets: number;
  generated_at: string;
};

/** How long before close a market is frozen. */
export type Snap = "24h" | "7d";
/** Showdown reveals the result (proof of concept); Live hides it (simulated product). */
export type View = "showdown" | "live";
export const snapLabel: Record<Snap, string> = { "24h": "24 hours", "7d": "7 days" };

type SnapshotData = Omit<
  Market,
  "id" | "question" | "category" | "closes_at" | "resolved_at" | "outcome" | "source_url"
>;
type RawMarket = Pick<Market, "id" | "question" | "category" | "closes_at"> & {
  resolved_at: string;
  outcome: "yes" | "no";
  source_url: string | null;
  snapshots: Partial<Record<Snap, SnapshotData>>;
};
const rawMarkets = raw as unknown as RawMarket[];

function atSnapshot(r: RawMarket, snap: Snap): Market | undefined {
  const s = r.snapshots[snap];
  if (!s) return undefined;
  const { snapshots: _ignored, ...base } = r;
  return { ...base, ...s };
}

// Resolved 2026 markets, each frozen 24 hours or 7 days before it closed.
export async function getMarkets(snap: Snap = "24h"): Promise<Market[]> {
  return rawMarkets.flatMap((r) => atSnapshot(r, snap) ?? []);
}
/** The market at this snapshot, plus which snapshots exist for it (undefined if the id is unknown). */
export async function getMarket(
  id: string,
  snap: Snap = "24h",
): Promise<{ market: Market | undefined; question: string; snaps: Snap[] } | undefined> {
  const r = rawMarkets.find((m) => m.id === id);
  if (!r) return undefined;
  return {
    market: atSnapshot(r, snap),
    question: r.question,
    snaps: Object.keys(r.snapshots) as Snap[],
  };
}

// Full YES price history per market (the data behind Polymarket's chart), loaded only when needed.
const priceFiles = import.meta.glob<{ points: [number, number][] }>("../data/prices/*.json", {
  import: "default",
});
/** [unix seconds, YES price] for the whole life of the market. */
export async function getPriceHistory(id: string): Promise<[number, number][]> {
  const load = priceFiles[`../data/prices/${id}.json`];
  return load ? (await load()).points : [];
}

export type NewsHeadline = { title: string; publisher: string; date: string; url: string };

export async function getMarketNews(market: Pick<Market, "id" | "snapshot_at">) {
  if (!market.snapshot_at) return undefined;
  const { default: archive } = await import("@/data/browser-news.json");
  const byMarket: Record<string, Record<string, NewsHeadline[]>> = archive;
  return byMarket[market.id]?.[market.snapshot_at];
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

/** What the sharps' call says, before anyone knows the result. */
export function predictionText(m: Market): string {
  if (m.call === "YES" || m.call === "NO") return `Sharps lean ${m.call}`;
  if (tiersPending) return "Waiting for wallet ratings";
  return "Not enough sharp money to call";
}

/**
 * The tables where the sharps disagree most with the price: biggest absolute skill gap,
 * tables with a sharp call first. Uses only pre-snapshot data, so it is safe in Live mode.
 * Empty until wallet ratings give some table a skill gap.
 */
export function topDisagreements(markets: Market[], n = 3): Market[] {
  const withGap = markets.filter((m) => skillGap(m) !== null);
  const called = (m: Market) => (m.call === "YES" || m.call === "NO" ? 1 : 0);
  return [...withGap]
    .sort((a, b) => called(b) - called(a) || Math.abs(skillGap(b)!) - Math.abs(skillGap(a)!))
    .slice(0, n);
}

/** Search, category and sort for the Lobby list. */
export type LobbySort = "gap" | "volume" | "closing";
export function filterMarkets(
  markets: Market[],
  {
    query = "",
    category = "All",
    sort = "gap",
  }: { query?: string; category?: string; sort?: LobbySort },
): Market[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const absGap = (m: Market) => Math.abs(skillGap(m) ?? -1);
  return markets
    .filter((m) => category === "All" || m.category === category)
    .filter((m) => words.every((w) => `${m.question} ${m.category}`.toLowerCase().includes(w)))
    .sort((a, b) =>
      sort === "gap"
        ? absGap(b) - absGap(a) || b.volume_usd - a.volume_usd
        : sort === "volume"
          ? b.volume_usd - a.volume_usd
          : b.closes_at.localeCompare(a.closes_at),
    );
}

export type Reading = {
  kind: "yes-cheap" | "no-cheap" | "agree" | "no-signal";
  /** One short headline, e.g. "YES looks cheap" */
  headline: string;
  /** What the numbers mean, in plain language */
  means: string;
  /** What someone who trusts the sharps might consider. Information, not advice. */
  might: string;
};

/**
 * Plain-language reading of a skill gap. `share` is skilled money on YES (0–1, null if none),
 * `price` is the YES price (0–1). Shared by the How to Play page and every table.
 */
export function readGap(share: number | null, price: number): Reading {
  if (share === null)
    return {
      kind: "no-signal",
      headline: "No reliable signal",
      means: "There isn't enough skilled money at this table to say what the proven traders think.",
      might: "ignore the sharps here and judge the market on its own.",
    };
  const sharp = Math.round(share * 100);
  const yes = Math.round(price * 100);
  const gap = sharp - yes;
  if (Math.abs(gap) <= 5)
    return {
      kind: "agree",
      headline: "The price already matches the sharps",
      means: `Skilled money is ${sharp}% on YES and the price says ${yes}%. The crowd and the proven traders broadly agree.`,
      might: "do nothing: there's no edge either way.",
    };
  if (gap > 0)
    return {
      kind: "yes-cheap",
      headline: "YES looks cheap",
      means: `Skilled money is ${sharp}% on YES, but YES costs only ${yes}¢. The proven traders think YES is more likely than its price suggests.`,
      might: "buy YES, or keep YES shares they already hold.",
    };
  return {
    kind: "no-cheap",
    headline: "NO looks cheap",
    means: `Skilled money is ${sharp}% on YES, below the ${yes}% the YES price implies. A NO share costs ${100 - yes}¢, and the proven traders think NO is more likely than that price suggests.`,
    might: "buy NO, or sell YES shares they already hold.",
  };
}

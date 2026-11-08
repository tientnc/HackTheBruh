import { createServerFn } from "@tanstack/react-start";
import raw from "@/data/markets.json";
import rawMeta from "@/data/meta.json";
export { default as ratingSnapshot } from "@/data/sharp-ratings.json";

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
  /** Every skilled wallet's position at the snapshot, not just the biggest. */
  sharps?: { wallet: string; side: "yes" | "no"; stake_usd: number; entry_price: number }[];
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
  rated_wallets?: number;
  skilled_wallets?: number;
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
 * counting only real disagreements (gap over 5) backed by at least $100 of skilled money,
 * on markets still in doubt (YES between 3¢ and 97¢). At 0¢ a few cheap long-shot tickets
 * can make "skilled money" look 100% YES without anyone expecting YES to happen.
 * Uses only pre-snapshot data, so it is safe in Live mode. Empty until wallet ratings exist.
 */
export const MIN_DISAGREEMENT_SKILLED_USD = 100;
export function topDisagreements(markets: Market[], n = 3): Market[] {
  const real = markets.filter((m) => {
    const g = skillGap(m);
    return (
      g !== null &&
      Math.abs(g) > 5 &&
      m.yes_price >= 0.03 &&
      m.yes_price <= 0.97 &&
      m.yes.skilled_usd + m.no.skilled_usd >= MIN_DISAGREEMENT_SKILLED_USD
    );
  });
  return [...real].sort((a, b) => Math.abs(skillGap(b)!) - Math.abs(skillGap(a)!)).slice(0, n);
}

/** Search, category and sort for the Lobby list. */
/** "hits" (Showdown only): the sharps' correct calls first, then tables with no call, then misses. */
export type LobbySort = "hits" | "gap" | "volume" | "closing";
/** Filter by the sharps' prediction: any call, a YES or NO call, or no call (not enough skilled money). */
export type CallFilter = "all" | "called" | "YES" | "NO" | "none";
const hasCall = (m: Market) => m.call === "YES" || m.call === "NO";
const HIT_RANK = { hit: 0, none: 1, miss: 2 } as const;
export function filterMarkets(
  markets: Market[],
  {
    query = "",
    category = "All",
    sort = "gap",
    call = "all",
  }: { query?: string; category?: string; sort?: LobbySort; call?: CallFilter },
): Market[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const absGap = (m: Market) => Math.abs(skillGap(m) ?? -1);
  return markets
    .filter((m) => category === "All" || m.category === category)
    .filter((m) =>
      call === "all"
        ? true
        : call === "called"
          ? hasCall(m)
          : call === "none"
            ? !hasCall(m)
            : m.call === call,
    )
    .filter((m) => words.every((w) => `${m.question} ${m.category}`.toLowerCase().includes(w)))
    .sort((a, b) =>
      sort === "hits"
        ? HIT_RANK[callResult(a)] - HIT_RANK[callResult(b)] ||
          absGap(b) - absGap(a) ||
          b.volume_usd - a.volume_usd
        : sort === "gap"
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

export type GapBucket = {
  label: string;
  min: number;
  max: number;
  /** tables with a skill gap in this range */
  tables: number;
  /** how often the side the sharps favoured (relative to the price) won */
  sharpSideWon: number | null;
  /** the average price of that side, i.e. how often the crowd expected it to win */
  priceImplied: number | null;
};
export type ScoreboardData = {
  tables: number;
  crowd: { favouriteRight: number; favouriteTables: number; brier: number };
  calls: { made: number; right: number; crowdRightSameTables: number };
  buckets: GapBucket[];
  notable: Market[];
};

/** Same skill-gap ranges as the backtest (polyresearch/backtest/evaluate.py GAP_BUCKETS). */
const GAP_RANGES: [string, number, number][] = [
  ["Small gap (0–5)", 0, 5],
  ["Medium gap (5–15)", 5, 15],
  ["Big gap (15+)", 15, 101],
];

/**
 * The track record on resolved markets at one snapshot: how well the crowd's price did,
 * how often the sharps' calls were right, and whether bigger skill gaps were more reliable.
 */
export function scoreboard(markets: Market[]): ScoreboardData {
  const resolved = markets.filter((m) => m.outcome);
  const won = (m: Market, side: "yes" | "no") => m.outcome === side;
  const favourite = (m: Market): "yes" | "no" | null =>
    m.yes_price > 0.5 ? "yes" : m.yes_price < 0.5 ? "no" : null;

  const favTables = resolved.filter((m) => favourite(m) !== null);
  const brier =
    resolved.reduce((s, m) => s + (m.yes_price - (m.outcome === "yes" ? 1 : 0)) ** 2, 0) /
    Math.max(1, resolved.length);

  const called = resolved.filter((m) => m.call === "YES" || m.call === "NO");
  const calls = {
    made: called.length,
    right: called.filter((m) => won(m, m.call!.toLowerCase() as "yes" | "no")).length,
    crowdRightSameTables: called.filter((m) => {
      const f = favourite(m);
      return f !== null && won(m, f);
    }).length,
  };

  const buckets = GAP_RANGES.map(([label, min, max]) => {
    const inRange = resolved.filter((m) => {
      const g = skillGap(m);
      if (g === null) return false;
      const a = Math.abs(g);
      return min === 0 ? a <= max : a > min && a <= max;
    });
    const side = (m: Market): "yes" | "no" => ((skillGap(m) ?? 0) >= 0 ? "yes" : "no");
    const n = inRange.length;
    return {
      label,
      min,
      max,
      tables: n,
      sharpSideWon: n ? inRange.filter((m) => won(m, side(m))).length / n : null,
      priceImplied: n
        ? inRange.reduce((s, m) => s + (side(m) === "yes" ? m.yes_price : 1 - m.yes_price), 0) / n
        : null,
    };
  });

  return {
    tables: resolved.length,
    crowd: {
      favouriteRight: favTables.filter((m) => won(m, favourite(m)!)).length,
      favouriteTables: favTables.length,
      brier,
    },
    calls,
    buckets,
    notable: topDisagreements(resolved, 6),
  };
}

export type SharpHand = {
  id: string;
  question: string;
  side: "yes" | "no";
  stake_usd: number;
  entry_price: number;
  outcome?: "yes" | "no" | undefined;
};
export type SharpRow = {
  wallet: string;
  tables: number;
  staked: number;
  yes: number;
  no: number;
  /** Showdown only: hands whose side won, out of resolved hands */
  won: number;
  resolved: number;
  /** Average price paid for the side taken: the chance the market gave it */
  priceImplied: number | null;
  hands: SharpHand[];
};

/**
 * Every skilled wallet seated at these tables at the snapshot, most active first:
 * how many tables, how much it staked, which way it leaned, and how its hands turned out.
 */
export function sharpsBoard(markets: Market[]): SharpRow[] {
  const by = new Map<string, SharpHand[]>();
  for (const m of markets)
    for (const s of m.sharps ?? []) {
      const hands = by.get(s.wallet) ?? [];
      hands.push({ id: m.id, question: m.question, ...s, outcome: m.outcome });
      by.set(s.wallet, hands);
    }
  return [...by]
    .map(([wallet, hands]) => {
      const done = hands.filter((h) => h.outcome);
      return {
        wallet,
        tables: new Set(hands.map((h) => h.id)).size,
        staked: hands.reduce((t, h) => t + h.stake_usd, 0),
        yes: hands.filter((h) => h.side === "yes").length,
        no: hands.filter((h) => h.side === "no").length,
        won: done.filter((h) => h.side === h.outcome).length,
        resolved: done.length,
        priceImplied: done.length
          ? done.reduce((t, h) => t + h.entry_price, 0) / done.length
          : null,
        hands: hands.sort((a, b) => b.stake_usd - a.stake_usd),
      };
    })
    .sort((a, b) => b.tables - a.tables || b.staked - a.staked);
}

export type MoneyLine = { bets: number; perDollar: number | null };
export type FollowTheMoney = {
  sharps: MoneyLine;
  crowd: MoneyLine;
  /** The sharps' most profitable call */
  best: { market: Market; side: "yes" | "no"; price: number; perDollar: number } | null;
};

/**
 * The money test on resolved tables: $1 at the frozen price on each side, held to the result.
 * "sharps" follows every sharp call, "crowd" always backs the favourite. Tables priced at
 * 0.5¢ or less, or 99.5¢ or more, are left out: there is nothing to win there.
 */
export function followTheMoney(markets: Market[]): FollowTheMoney {
  const resolved = markets.filter((m) => m.outcome);
  const bet = (m: Market, side: "yes" | "no") => {
    const price = side === "yes" ? m.yes_price : 1 - m.yes_price;
    if (price <= 0.005 || price >= 0.995) return null;
    return { market: m, side, price, perDollar: m.outcome === side ? 1 / price - 1 : -1 };
  };
  const line = (bets: NonNullable<ReturnType<typeof bet>>[]): MoneyLine => ({
    bets: bets.length,
    perDollar: bets.length ? bets.reduce((t, b) => t + b.perDollar, 0) / bets.length : null,
  });
  const sharpBets = resolved.flatMap((m) =>
    m.call === "YES" || m.call === "NO" ? (bet(m, m.call === "YES" ? "yes" : "no") ?? []) : [],
  );
  const crowdBets = resolved.flatMap((m) =>
    m.yes_price === 0.5 ? [] : (bet(m, m.yes_price > 0.5 ? "yes" : "no") ?? []),
  );
  const best = [...sharpBets].sort((a, b) => b.perDollar - a.perDollar)[0];
  return {
    sharps: line(sharpBets),
    crowd: line(crowdBets),
    best: best && best.perDollar > 0 ? best : null,
  };
}

export const fmtCentsPerDollar = (x: number | null) =>
  x === null ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(Math.round(x * 100))}¢`;

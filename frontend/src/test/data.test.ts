import { describe, expect, it } from "vitest";
import {
  callResult,
  chipCount,
  chipUnit,
  featured,
  filterMarkets,
  readGap,
  scoreboard,
  followTheMoney,
  sharpsBoard,
  topDisagreements,
  fmtGap,
  fmtUsd,
  getMarkets,
  getPriceHistory,
  skillGap,
  suitFor,
  verdict,
  type CallFilter,
  type Market,
  type Side,
} from "@/lib/data";

const side = (skilled: number, unskilled = 0, unrated = 0): Side => ({
  skilled_usd: skilled,
  unskilled_usd: unskilled,
  new_usd: unrated,
  skilled_wallets: skilled ? 3 : 0,
  unskilled_wallets: unskilled ? 3 : 0,
  new_wallets: unrated ? 3 : 0,
});
const market = (
  id: string,
  yes: Side,
  no: Side,
  yes_price: number,
  extra: Partial<Market> = {},
): Market => ({
  id,
  question: id,
  category: "Equities",
  closes_at: "2026-01-14T14:00:00Z",
  yes_price,
  volume_usd: 1000,
  yes,
  no,
  skilled_share_history: [],
  top_positions: [],
  ...extra,
});

describe("skill gap", () => {
  it("78% skilled YES at 54¢ is +24", () =>
    expect(skillGap(market("a", side(410), side(115), 0.54))).toBe(24));
  it("15% skilled YES at 31¢ is -16", () =>
    expect(skillGap(market("b", side(30), side(170), 0.31))).toBe(-16));
  it("no skilled money means no gap", () =>
    expect(skillGap(market("c", side(0, 50), side(0, 70), 0.4))).toBeNull());
  it("formats with a real minus sign", () => {
    expect(fmtGap(24)).toBe("+24");
    expect(fmtGap(-16)).toBe("−16");
    expect(fmtGap(null)).toBe("?");
  });
});

describe("featured table", () => {
  it("prefers the biggest gap among tables with a sharp call", () => {
    const ms = [
      market("big-no-call", side(900), side(100), 0.1, { call: "INSUFFICIENT" }),
      market("called", side(700), side(300), 0.5, { call: "YES" }),
    ];
    expect(featured(ms).id).toBe("called");
  });
  it("falls back to volume when nobody is rated", () => {
    const ms = [
      market("small", side(0, 5), side(0, 5), 0.5),
      market("large", side(0, 5), side(0, 5), 0.5, { volume_usd: 9999 }),
    ];
    expect(featured(ms).id).toBe("large");
  });
});

describe("showdown", () => {
  it("marks a correct call as a hit", () => {
    expect(callResult(market("h", side(1), side(1), 0.5, { call: "NO", outcome: "no" }))).toBe(
      "hit",
    );
    expect(callResult(market("m", side(1), side(1), 0.5, { call: "YES", outcome: "no" }))).toBe(
      "miss",
    );
    expect(
      callResult(market("n", side(1), side(1), 0.5, { call: "INSUFFICIENT", outcome: "no" })),
    ).toBe("none");
  });
});

describe("suits and verdicts", () => {
  it("within ±5 is a spade and agree", () => {
    expect(suitFor(5)).toBe("♠");
    expect(verdict(-5)).toBe("Sharps and the house agree");
  });
  it("positive club, negative diamond", () => {
    expect(suitFor(6)).toBe("♣");
    expect(suitFor(-6)).toBe("♦");
    expect(verdict(-6)).toBe("Sharps are more confident in NO than the house");
  });
});

describe("chips", () => {
  it("scales each table so the biggest stack is about 10 chips", () => {
    expect(chipUnit(market("u", side(410_000), side(115_000), 0.5))).toBe(50_000);
    expect(chipUnit(market("v", side(0, 3728), side(0, 1490), 0.5))).toBe(500);
  });
  it("no money, no chips; otherwise 1 to 12", () => {
    expect(chipCount(0, 500)).toBe(0);
    expect(chipCount(50, 500)).toBe(1);
    expect(chipCount(3728, 500)).toBe(7);
    expect(chipCount(2_000_000, 500)).toBe(12);
  });
  it("formats small amounts in dollars", () => {
    expect(fmtUsd(620)).toBe("$620");
    expect(fmtUsd(38_329)).toBe("$38k");
    expect(fmtUsd(1_130_000)).toBe("$1.13M");
  });
});

describe("generated lobby data", () => {
  for (const snap of ["24h", "7d"] as const) {
    it(`${snap}: resolved markets frozen before close, with prices and sparklines`, async () => {
      const ms = await getMarkets(snap);
      expect(ms.length).toBeGreaterThan(0);
      expect(new Set(ms.map((m) => m.id)).size).toBe(ms.length);
      for (const m of ms) {
        expect(["yes", "no"]).toContain(m.outcome);
        expect(m.yes_price).toBeGreaterThanOrEqual(0);
        expect(m.yes_price).toBeLessThanOrEqual(1);
        expect(m.snapshot_at! < m.closes_at).toBe(true);
        // no peeking: the small chart never goes past the snapshot
        const snapTs = new Date(m.snapshot_at!).getTime() / 1000;
        for (const [t] of m.spark ?? []) expect(t).toBeLessThanOrEqual(snapTs);
      }
    });
  }
  it("7 days before is earlier than 24 hours before", async () => {
    const day = new Map((await getMarkets("24h")).map((m) => [m.id, m]));
    for (const m of await getMarkets("7d")) {
      const d = day.get(m.id);
      if (d) expect(m.snapshot_at! < d.snapshot_at!).toBe(true);
    }
  });
  it("loads a market's full price history", async () => {
    const [m] = await getMarkets("24h");
    const pts = await getPriceHistory(m!.id);
    expect(pts.length).toBeGreaterThan(1);
  });
});

describe("lobby lists", () => {
  const ms = [
    market("fed", side(700), side(300), 0.5, {
      call: "YES",
      question: "Fed cut in March?",
      category: "Rates & macro",
    }),
    market("gold", side(100), side(900), 0.6, {
      call: "INSUFFICIENT",
      question: "Gold above $5,000?",
      category: "Commodities",
    }),
    market("apple", side(0, 10), side(0, 10), 0.5, {
      question: "Apple largest company?",
      volume_usd: 9_000,
    }),
    market("oil", side(450), side(550), 0.5, {
      call: "NO",
      question: "Oil above $90?",
      category: "Commodities",
    }),
  ];
  it("biggest disagreements: real gaps (over 5) with enough skilled money, biggest first", () => {
    expect(topDisagreements(ms).map((m) => m.id)).toEqual(["gold", "fed"]);
    expect(topDisagreements([ms[2]!])).toEqual([]);
    // a near-certain market (YES at 1¢) never counts, however lopsided the cheap tickets look
    expect(topDisagreements([market("lotto", side(900), side(0), 0.01)])).toEqual([]);
  });
  it("search matches every word, case-insensitive", () => {
    expect(filterMarkets(ms, { query: "gold 5,000" }).map((m) => m.id)).toEqual(["gold"]);
    expect(filterMarkets(ms, { query: "FED" }).map((m) => m.id)).toEqual(["fed"]);
  });
  it("filters by the sharps' call", () => {
    const ids = (call: CallFilter) =>
      filterMarkets(ms, { call })
        .map((m) => m.id)
        .sort();
    expect(ids("YES")).toEqual(["fed"]);
    expect(ids("NO")).toEqual(["oil"]);
    expect(ids("called")).toEqual(["fed", "oil"]);
    expect(ids("none")).toEqual(["apple", "gold"]);
    expect(ids("all")).toHaveLength(4);
  });
  it("category filter and sorts", () => {
    expect(
      filterMarkets(ms, { category: "Commodities" })
        .map((m) => m.id)
        .sort(),
    ).toEqual(["gold", "oil"]);
    expect(filterMarkets(ms, { sort: "volume" })[0]!.id).toBe("apple");
    expect(filterMarkets(ms, { sort: "gap" }).at(-1)!.id).toBe("apple");
  });
});

describe("plain-language readings", () => {
  it("covers every kind of table", () => {
    expect(readGap(0.78, 0.54).kind).toBe("yes-cheap");
    expect(readGap(0.15, 0.31).kind).toBe("no-cheap");
    expect(readGap(0.7, 0.67).kind).toBe("agree");
    expect(readGap(null, 0.4).kind).toBe("no-signal");
  });
  it("the trap: sharps mostly on YES but YES dearer than they think reads as NO-cheap", () => {
    const r = readGap(0.78, 0.9);
    expect(r.kind).toBe("no-cheap");
    expect(r.means).toContain("NO share costs 10¢");
  });
  it("uses the same ±5 boundary as the verdict", () => {
    expect(readGap(0.59, 0.54).kind).toBe("agree");
    expect(readGap(0.6, 0.54).kind).toBe("yes-cheap");
  });
});

describe("scoreboard", () => {
  const ms = [
    // sharps 70% vs 50¢ → +20, called YES, YES won
    market("a", side(700), side(300), 0.5, { call: "YES", outcome: "yes" }),
    // sharps 20% vs 60¢ → −40, called NO, YES won (miss); crowd favourite YES was right
    market("b", side(200), side(800), 0.6, { call: "NO", outcome: "yes" }),
    // sharps 52% vs 50¢ → +2 (small), no call, NO won
    market("c", side(520), side(480), 0.5, { call: "INSUFFICIENT", outcome: "no" }),
    // unrated, crowd favourite NO (20¢), NO won
    market("d", side(0, 10), side(0, 10), 0.2, { outcome: "no" }),
  ];
  const s = scoreboard(ms);
  it("crowd baseline counts only tables with a favourite", () => {
    expect(s.crowd.favouriteTables).toBe(2);
    expect(s.crowd.favouriteRight).toBe(2);
    expect(s.crowd.brier).toBeCloseTo((0.25 + 0.16 + 0.25 + 0.04) / 4);
  });
  it("sharps' calls compared with the crowd on the same tables", () => {
    expect(s.calls).toEqual({ made: 2, right: 1, crowdRightSameTables: 1 });
  });
  it("buckets by gap size, sharp side vs price-implied chance", () => {
    const [small, medium, big] = s.buckets;
    expect(small!.tables).toBe(1);
    expect(small!.sharpSideWon).toBe(0);
    expect(medium!.tables).toBe(0);
    expect(medium!.sharpSideWon).toBeNull();
    expect(big!.tables).toBe(2);
    expect(big!.sharpSideWon).toBe(0.5);
    expect(big!.priceImplied).toBeCloseTo((0.5 + 0.4) / 2);
  });
});

describe("the sharps", () => {
  const seat = (wallet: string, side: "yes" | "no", stake_usd: number, entry_price: number) => ({
    wallet,
    side,
    stake_usd,
    entry_price,
  });
  const ms = [
    market("a", side(1), side(1), 0.5, {
      outcome: "yes",
      sharps: [seat("0xA", "yes", 300, 0.4), seat("0xB", "no", 50, 0.6)],
    }),
    market("b", side(1), side(1), 0.5, { outcome: "no", sharps: [seat("0xA", "yes", 100, 0.2)] }),
  ];
  it("groups hands per wallet, most tables first, with how they turned out", () => {
    const [a, b] = sharpsBoard(ms);
    expect(a).toMatchObject({
      wallet: "0xA",
      tables: 2,
      staked: 400,
      yes: 2,
      no: 0,
      won: 1,
      resolved: 2,
    });
    expect(a!.priceImplied).toBeCloseTo(0.3);
    expect(a!.hands[0]!.id).toBe("a");
    expect(b).toMatchObject({ wallet: "0xB", tables: 1, won: 0 });
  });
  it("no sharps, empty board", () =>
    expect(sharpsBoard([market("c", side(1), side(1), 0.5)])).toEqual([]));
});

describe("follow the money", () => {
  const ms = [
    // sharps call YES at 10¢, YES wins: +$9 per $1; crowd backs NO at 90¢ and loses $1
    market("long", side(900), side(100), 0.1, { call: "YES", outcome: "yes" }),
    // sharps call NO at 40¢ (YES 60¢), YES wins: −$1; crowd backs YES at 60¢: +67¢
    market("miss", side(100), side(900), 0.6, { call: "NO", outcome: "yes" }),
    // near-certain: left out of both
    market("sure", side(900), side(100), 0.999, { call: "YES", outcome: "yes" }),
  ];
  const f = followTheMoney(ms);
  it("averages $1 bets at the frozen price, leaving out near-certain tables", () => {
    expect(f.sharps.bets).toBe(2);
    expect(f.sharps.perDollar).toBeCloseTo((9 - 1) / 2);
    expect(f.crowd.bets).toBe(2);
    expect(f.crowd.perDollar).toBeCloseTo((-1 + (1 / 0.6 - 1)) / 2);
    expect(f.best!.market.id).toBe("long");
  });
  it("sorts the sharps' correct calls first in Showdown", () => {
    expect(
      filterMarkets(ms, { sort: "hits" })
        .map((m) => m.id)
        .at(-1),
    ).toBe("miss");
  });
});

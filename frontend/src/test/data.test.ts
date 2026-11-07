import { describe, expect, it } from "vitest";
import raw from "@/data/markets.json";
import {
  callResult,
  chipCount,
  chipUnit,
  featured,
  fmtGap,
  fmtUsd,
  skillGap,
  suitFor,
  verdict,
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
  it("within ±5 is a heart and agree", () => {
    expect(suitFor(5)).toBe("♥");
    expect(verdict(-5)).toBe("Sharps and the house agree");
  });
  it("positive spade, negative club", () => {
    expect(suitFor(6)).toBe("♠");
    expect(suitFor(-6)).toBe("♣");
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
  const ms = raw as Market[];
  it("has resolved markets with outcomes and snapshot prices", () => {
    expect(ms.length).toBeGreaterThan(0);
    for (const m of ms) {
      expect(["yes", "no"]).toContain(m.outcome);
      expect(m.yes_price).toBeGreaterThanOrEqual(0);
      expect(m.yes_price).toBeLessThanOrEqual(1);
      expect(m.snapshot_at! < m.closes_at).toBe(true);
    }
  });
  it("has unique ids", () => expect(new Set(ms.map((m) => m.id)).size).toBe(ms.length));
});

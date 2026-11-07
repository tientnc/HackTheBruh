import { describe, expect, it } from "vitest";
import raw from "@/data/markets.json";
import { chipCount, skillGap, suitFor, verdict, featured, type Market } from "@/lib/data";

const ms = raw as Market[];
const by = (id: string) => ms.find((m) => m.id === id)!;

describe("skill gap", () => {
  it("Fed market is +24", () => expect(skillGap(by("fed-dec-cut"))).toBe(24));
  it("Bitcoin market is -16", () => expect(skillGap(by("btc-120k"))).toBe(-16));
  it("Climate market is +3", () => expect(skillGap(by("warmest-2026"))).toBe(3));
  it("featured is largest absolute gap", () => {
    const f = featured(ms);
    expect(ms.every((m) => Math.abs(skillGap(m)) <= Math.abs(skillGap(f)))).toBe(true);
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
  it("1 chip per $40k, min 1, max 12", () => {
    expect(chipCount(5000)).toBe(1);
    expect(chipCount(410000)).toBe(10);
    expect(chipCount(2_000_000)).toBe(12);
  });
});

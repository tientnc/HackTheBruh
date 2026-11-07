import raw from "@/data/markets.json";

export type Tier = "skilled" | "unskilled" | "new";
export type Side = {
  skilled_usd: number;
  unskilled_usd: number;
  new_usd: number;
  skilled_wallets: number;
  unskilled_wallets: number;
  new_wallets: number;
};
export type Market = {
  id: string;
  question: string;
  category: string;
  closes_at: string;
  yes_price: number;
  volume_usd: number;
  yes: Side;
  no: Side;
  skilled_share_history: { date: string; skilled_yes_share: number; yes_price: number }[];
  top_positions: { wallet: string; tier: Tier; side: "yes" | "no"; stake_usd: number; entry_price: number }[];
};

// Single data entry point: swap this for a fetch to the real markets.json or an API.
export async function getMarkets(): Promise<Market[]> {
  return raw as Market[];
}
export async function getMarket(id: string): Promise<Market | undefined> {
  return (await getMarkets()).find((m) => m.id === id);
}

export function skilledYesShare(m: Pick<Market, "yes" | "no">): number {
  const total = m.yes.skilled_usd + m.no.skilled_usd;
  return total === 0 ? 0 : m.yes.skilled_usd / total;
}
export function skillGap(m: Pick<Market, "yes" | "no" | "yes_price">): number {
  return Math.round(skilledYesShare(m) * 100 - m.yes_price * 100);
}
export function verdict(gap: number): string {
  if (Math.abs(gap) <= 5) return "Sharps and the house agree";
  return gap > 0
    ? "Sharps are more confident in YES than the house"
    : "Sharps are more confident in NO than the house";
}
export function suitFor(gap: number): "♠" | "♣" | "♥" {
  if (Math.abs(gap) <= 5) return "♥";
  return gap > 0 ? "♠" : "♣";
}
export function chipCount(usd: number): number {
  return Math.min(12, Math.max(1, Math.round(usd / 40000)));
}
export function featured(markets: Market[]): Market {
  return [...markets].sort((a, b) => Math.abs(skillGap(b)) - Math.abs(skillGap(a)))[0]!;
}
export const sideTotal = (s: Side) => s.skilled_usd + s.unskilled_usd + s.new_usd;
export const fmtUsd = (n: number) =>
  n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(2)}M` : `$${Math.round(n / 1000)}k`;
export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
export const shortWallet = (w: string) => `${w.slice(0, 4)}…${w.slice(-2)}`;
export const cents = (p: number) => `${Math.round(p * 100)}¢`;

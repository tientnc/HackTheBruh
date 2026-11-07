import { chipCount, fmtUsd, type Tier } from "@/lib/data";
import { cn } from "@/lib/utils";

const chipClass: Record<Tier, string> = {
  skilled: "bg-chip-skilled border-chip-skilled-edge",
  unskilled: "bg-chip-unskilled border-chip-unskilled-edge",
  new: "bg-chip-new border-chip-new-edge",
};
// "new" = wallets with no rating yet (not in the tiers file).
export const tierLabel: Record<Tier, string> = {
  skilled: "Skilled",
  unskilled: "Unskilled",
  new: "Unrated",
};

export function Chip({ tier, className }: { tier: Tier; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-4 w-10 rounded-[50%] border-2 border-dashed shadow-[0_2px_2px_rgb(0_0_0/0.45)]",
        chipClass[tier],
        className,
      )}
    />
  );
}

export function ChipStack({
  tier,
  usd,
  wallets,
  unit,
}: {
  tier: Tier;
  usd: number;
  wallets?: number;
  unit?: number;
}) {
  const n = chipCount(usd, unit);
  return (
    <div className="flex flex-col items-center gap-1">
      <div aria-hidden className="flex h-36 flex-col-reverse items-center justify-start">
        {Array.from({ length: n }).map((_, i) => (
          <Chip key={i} tier={tier} className="-mt-2 first:mt-0" />
        ))}
      </div>
      <span className="text-xs font-semibold text-text-2">{tierLabel[tier]}</span>
      <span className="font-display text-lg text-foreground">{fmtUsd(usd)}</span>
      {wallets !== undefined && (
        <span className="text-[11px] text-text-3">{wallets.toLocaleString()} wallets</span>
      )}
    </div>
  );
}

export function Legend({ unit }: { unit?: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-text-2">
      {(["skilled", "unskilled", "new"] as Tier[]).map((t) => (
        <span key={t} className="flex items-center gap-2">
          <Chip tier={t} /> {t === "new" ? "Unrated wallets" : tierLabel[t]}
        </span>
      ))}
      {unit !== undefined && (
        <span className="text-text-3">1 chip ≈ {fmtUsd(unit)} at this table</span>
      )}
    </div>
  );
}

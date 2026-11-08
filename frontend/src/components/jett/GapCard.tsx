import { fmtGap, suitFor } from "@/lib/data";
import { cn } from "@/lib/utils";

type Props = {
  gap?: number | null;
  rank?: string;
  suit?: "♠" | "♣" | "♥" | "♦";
  size?: "sm" | "md" | "lg";
  tilt?: number;
  label?: string;
};

const sizes = { sm: "h-20 w-14 text-xl", md: "h-32 w-24 text-3xl", lg: "h-44 w-32 text-5xl" };

export function GapCard({ gap, rank, suit, size = "md", tilt = -6, label }: Props) {
  const isGap = gap !== undefined;
  const s = suit ?? suitFor(gap ?? null);
  const value = rank ?? (isGap ? fmtGap(gap) : "");
  const red = s === "♦" || s === "♥";
  const ink = red ? "text-card-red" : "text-card-ink";
  const aria =
    label ??
    (isGap
      ? gap === null
        ? "No skill gap: not enough rated money at this table"
        : `Skill gap ${value} points`
      : `${rank} of ${s}`);
  return (
    <div
      role="img"
      aria-label={aria}
      className={cn("playing-card relative flex items-center justify-center", sizes[size])}
      style={{ transform: `rotate(${tilt}deg)` }}
    >
      <span
        aria-hidden
        className={cn("absolute left-1.5 top-1 text-left text-[11px] font-bold leading-tight", ink)}
      >
        {value}
        <br />
        {s}
      </span>
      <span aria-hidden className={cn("font-display", ink)}>
        {value}
      </span>
      <span
        aria-hidden
        className={cn(
          "absolute bottom-1 right-1.5 rotate-180 text-left text-[11px] font-bold leading-tight",
          ink,
        )}
      >
        {value}
        <br />
        {s}
      </span>
    </div>
  );
}

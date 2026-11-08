import { useId, useState } from "react";
import { readGap } from "@/lib/data";
import { GapCard } from "./GapCard";

/** Try-it calculator: move the price and the sharps' share, see the skill gap and what it means. */
export function GapCalculator() {
  const [price, setPrice] = useState(54);
  const [sharp, setSharp] = useState(78);
  const priceId = useId();
  const sharpId = useId();
  const gap = sharp - price;
  const r = readGap(sharp / 100, price / 100);

  return (
    <div className="grid items-center gap-8 md:grid-cols-[1fr_auto]">
      <div className="space-y-6">
        <div className="space-y-2">
          <label htmlFor={priceId} className="flex justify-between text-sm text-text-2">
            <span>YES price (the crowd's guess)</span>
            <span className="font-semibold text-foreground">{price}¢</span>
          </label>
          <input
            id={priceId}
            type="range"
            min={1}
            max={99}
            value={price}
            onChange={(e) => setPrice(Number(e.target.value))}
            className="w-full accent-[var(--gold)]"
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={sharpId} className="flex justify-between text-sm text-text-2">
            <span>Skilled money on YES</span>
            <span className="font-semibold text-foreground">{sharp}%</span>
          </label>
          <input
            id={sharpId}
            type="range"
            min={0}
            max={100}
            value={sharp}
            onChange={(e) => setSharp(Number(e.target.value))}
            className="w-full accent-[var(--gold)]"
          />
        </div>
        <div
          className="space-y-2 rounded-xl border border-border bg-background/40 p-4"
          aria-live="polite"
        >
          <p className="text-sm text-text-3">
            Skill gap = {sharp}% − {price} ={" "}
            <strong className="text-foreground">
              {gap > 0 ? `+${gap}` : gap < 0 ? `−${-gap}` : "0"}
            </strong>
          </p>
          <p className="text-xl text-gold-light">{r.headline}</p>
          <p className="text-sm text-text-2">{r.means}</p>
          <p className="text-sm text-text-2">
            <strong className="text-foreground">Someone who trusts the sharps might</strong>{" "}
            {r.might}
          </p>
        </div>
      </div>
      <div className="flex justify-center">
        <GapCard gap={gap} size="lg" tilt={-4} />
      </div>
    </div>
  );
}

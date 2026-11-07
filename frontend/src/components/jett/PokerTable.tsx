import {
  callResult,
  cents,
  chipUnit,
  fmtUsd,
  sideTotal,
  skillGap,
  skilledYesShare,
  tiersPending,
  type Market,
} from "@/lib/data";
import { ChipStack } from "./Chips";
import { GapCard } from "./GapCard";

function TableSide({ m, side, unit }: { m: Market; side: "yes" | "no"; unit: number }) {
  const s = m[side];
  const price = side === "yes" ? m.yes_price : 1 - m.yes_price;
  return (
    <div className="flex flex-col items-center gap-3">
      <h3 className="text-3xl text-gold-light">{side.toUpperCase()}</h3>
      <p className="text-center text-sm text-text-2">
        {fmtUsd(sideTotal(s))} on the felt · {cents(price)} a share
      </p>
      <div className="flex items-end gap-4 sm:gap-6">
        <ChipStack tier="skilled" usd={s.skilled_usd} wallets={s.skilled_wallets} unit={unit} />
        <ChipStack
          tier="unskilled"
          usd={s.unskilled_usd}
          wallets={s.unskilled_wallets}
          unit={unit}
        />
        <ChipStack tier="new" usd={s.new_usd} wallets={s.new_wallets} unit={unit} />
      </div>
    </div>
  );
}

export function callLine(m: Market): string {
  const r = callResult(m);
  if (r === "hit") return `Sharps called ${m.call}, and they were right.`;
  if (r === "miss") return `Sharps called ${m.call}, and they were wrong.`;
  if (tiersPending) return "Sharps' call appears once wallet ratings are added.";
  return "Not enough sharp money to make a call.";
}

export function Showdown({ m }: { m: Market }) {
  if (!m.outcome) return null;
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="rounded-full bg-gold px-3 py-1 text-xs font-bold uppercase tracking-widest text-primary-foreground">
        Showdown: {m.outcome.toUpperCase()} won
      </span>
      <span className="text-xs text-text-2">{callLine(m)}</span>
    </div>
  );
}

export function PokerTable({ m }: { m: Market }) {
  const gap = skillGap(m);
  const share = skilledYesShare(m);
  const unit = chipUnit(m);
  return (
    <div className="rail rounded-[3rem] p-3 sm:p-5 md:rounded-[999px]">
      <div className="felt grid items-center gap-8 rounded-[2.4rem] px-6 py-10 md:grid-cols-[1fr_auto_1fr] md:rounded-[999px] md:px-16">
        <TableSide m={m} side="yes" unit={unit} />
        <div className="flex max-w-60 flex-col items-center gap-4 text-center">
          <GapCard gap={gap} size="lg" />
          <span className="caption">Skill gap</span>
          <p className="text-sm text-text-2">
            {share === null
              ? `No rated sharps at this table yet. The house priced YES at ${cents(m.yes_price)}.`
              : `Sharps had ${Math.round(share * 100)}% of their chips on YES. The house priced YES at ${cents(m.yes_price)}.`}
          </p>
          <Showdown m={m} />
        </div>
        <TableSide m={m} side="no" unit={unit} />
      </div>
    </div>
  );
}

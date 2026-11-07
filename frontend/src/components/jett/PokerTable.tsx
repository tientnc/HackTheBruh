import { cents, fmtUsd, sideTotal, skillGap, skilledYesShare, type Market } from "@/lib/data";
import { ChipStack } from "./Chips";
import { GapCard } from "./GapCard";

function TableSide({ m, side }: { m: Market; side: "yes" | "no" }) {
  const s = m[side];
  const price = side === "yes" ? m.yes_price : 1 - m.yes_price;
  return (
    <div className="flex flex-col items-center gap-3">
      <h3 className="text-3xl text-gold-light">{side.toUpperCase()}</h3>
      <p className="text-center text-sm text-text-2">
        {fmtUsd(sideTotal(s))} on the felt · {cents(price)} a share
      </p>
      <div className="flex items-end gap-4 sm:gap-6">
        <ChipStack tier="skilled" usd={s.skilled_usd} wallets={s.skilled_wallets} />
        <ChipStack tier="unskilled" usd={s.unskilled_usd} wallets={s.unskilled_wallets} />
        <ChipStack tier="new" usd={s.new_usd} wallets={s.new_wallets} />
      </div>
    </div>
  );
}

export function PokerTable({ m }: { m: Market }) {
  const gap = skillGap(m);
  const share = Math.round(skilledYesShare(m) * 100);
  return (
    <div className="rail rounded-[3rem] p-3 sm:p-5 md:rounded-[999px]">
      <div className="felt grid items-center gap-8 rounded-[2.4rem] px-6 py-10 md:grid-cols-[1fr_auto_1fr] md:rounded-[999px] md:px-16">
        <TableSide m={m} side="yes" />
        <div className="flex max-w-56 flex-col items-center gap-4 text-center">
          <GapCard gap={gap} size="lg" />
          <span className="caption">Skill gap</span>
          <p className="text-sm text-text-2">
            Sharps have {share}% of their chips on YES. The house prices YES at {cents(m.yes_price)}.
          </p>
        </div>
        <TableSide m={m} side="no" />
      </div>
    </div>
  );
}

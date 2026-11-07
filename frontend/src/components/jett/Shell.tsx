import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

const links = [
  { to: "/", label: "Lobby" },
  { to: "/sharps", label: "The Sharps" },
  { to: "/scoreboard", label: "Scoreboard" },
  { to: "/house-rules", label: "House Rules" },
] as const;

export function Header() {
  return (
    <header className="border-b border-border">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-5">
        <Link to="/" className="flex flex-col leading-none">
          <span className="font-display text-3xl text-gold">JETT SHOWDOWN</span>
          <span className="caption mt-1 text-[10px]">Table stakes</span>
        </Link>
        <nav aria-label="Main" className="flex flex-wrap gap-2">
          {links.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              activeOptions={{ exact: l.to === "/" }}
              className="rounded-full border border-border px-4 py-1.5 text-sm text-text-2 transition-colors hover:border-gold hover:text-gold-light"
              activeProps={{ className: "!bg-gold !text-primary-foreground !border-gold font-semibold" }}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="mt-20 border-t border-border">
      <p className="mx-auto max-w-6xl px-4 py-6 text-center text-sm text-text-3">
        For information only. Not financial advice. Past performance does not predict future results.
      </p>
    </footer>
  );
}

export const goldLinkClass =
  "inline-flex items-center rounded-full bg-gold px-6 py-3 font-semibold text-primary-foreground shadow-lg transition-transform hover:-translate-y-0.5";

export function GoldLink({ children }: { children: ReactNode; to: "/" }) {
  return (
    <Link to="/" className={goldLinkClass}>
      {children}
    </Link>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-border bg-panel p-6 ${className}`}>{children}</section>;
}

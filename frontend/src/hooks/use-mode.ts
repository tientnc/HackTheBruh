import { useNavigate, useSearch } from "@tanstack/react-router";
import type { Snap, View } from "@/lib/data";

type ModeSearch = { view?: View; at?: Snap; news?: "on" | "off" };

/** The app-wide toggles, read from the URL (?view=live&at=7d&news=on). */
export function useMode() {
  const search = useSearch({ strict: false }) as ModeSearch;
  const navigate = useNavigate();
  const view = search.view ?? "showdown";
  const at = search.at ?? "24h";
  const set = (next: ModeSearch) =>
    void navigate({
      to: ".",
      search: ((prev: Record<string, unknown>) => ({ ...prev, view, at, ...next })) as never,
      replace: true,
      resetScroll: false,
    });
  return { view, at, news: search.news === "on", set };
}

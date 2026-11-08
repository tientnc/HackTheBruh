import { useNavigate, useSearch } from "@tanstack/react-router";
import type { Snap, View } from "@/lib/data";

/** The app-wide toggles, read from the URL (?view=live&at=7d). */
export function useMode(): {
  view: View;
  at: Snap;
  set: (next: { view?: View; at?: Snap }) => void;
} {
  const search = useSearch({ strict: false }) as { view?: View; at?: Snap };
  const navigate = useNavigate();
  const view = search.view ?? "showdown";
  const at = search.at ?? "24h";
  const set = (next: { view?: View; at?: Snap }) =>
    void navigate({
      to: ".",
      search: ((prev: Record<string, unknown>) => ({ ...prev, view, at, ...next })) as never,
      replace: true,
      resetScroll: false,
    });
  return { view, at, set };
}

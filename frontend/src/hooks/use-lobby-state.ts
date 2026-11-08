import { useEffect, useState } from "react";
import type { CallFilter, LobbySort } from "@/lib/data";

export type LobbyState = {
  query: string;
  category: string;
  call: CallFilter;
  sort: LobbySort;
  shown: number;
};
const KEY = "jett-lobby";
const SCROLL_KEY = "jett-lobby-scroll";
export const LOBBY_PAGE = 12;
const initial: LobbyState = {
  query: "",
  category: "All",
  call: "all",
  sort: "gap",
  shown: LOBBY_PAGE,
};

function read<T>(key: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
function write(key: string, value: unknown) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage unavailable (private mode etc.): the Lobby still works, it just won't remember
  }
}

/** Remember where the Lobby was when you open a table: scroll position, kept for this tab only. */
export function rememberLobbyScroll() {
  write(SCROLL_KEY, window.scrollY);
}

/**
 * Search, filter, sort and how many tables are shown, remembered for this browser tab so
 * "Back to the Lobby" returns you to the same view. The toggles (mode, snapshot) live in the URL.
 */
export function useLobbyState(): [LobbyState, (next: Partial<LobbyState>) => void] {
  const [state, setState] = useState<LobbyState>(initial);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const saved = read<Partial<LobbyState>>(KEY);
    if (saved) setState((s) => ({ ...s, ...saved }));
    setLoaded(true);
    const y = read<number>(SCROLL_KEY);
    if (typeof y === "number" && y > 0) {
      window.sessionStorage.removeItem(SCROLL_KEY);
      // wait for the restored list to render, then return to where the visitor was
      requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo(0, y)));
    }
  }, []);

  useEffect(() => {
    if (loaded) write(KEY, state);
  }, [state, loaded]);

  return [state, (next) => setState((s) => ({ ...s, ...next }))];
}

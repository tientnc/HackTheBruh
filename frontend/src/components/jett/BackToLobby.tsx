import { Link } from "@tanstack/react-router";

/** Back to the Lobby, keeping the mode and snapshot (they ride along in the URL). */
export function BackToLobby() {
  return (
    <Link
      to="/"
      className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border px-4 text-sm text-text-2 transition-colors hover:border-gold hover:text-gold-light"
    >
      <svg aria-hidden width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path
          d="M10 3 5 8l5 5"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      Back to the Lobby
    </Link>
  );
}

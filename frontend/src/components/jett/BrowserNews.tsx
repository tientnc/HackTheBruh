import type { NewsHeadline } from "@/lib/data";
import { Panel } from "@/components/jett/Shell";

export function BrowserNews({ headlines }: { headlines: NewsHeadline[] | undefined }) {
  return (
    <Panel>
      <p className="caption">Experimental</p>
      <h2 className="text-2xl text-gold-light">Browser Integration</h2>
      <p className="mt-1 text-sm text-text-3">
        Related headlines from the seven complete days before this snapshot (UTC). The prediction
        stays the same.
      </p>
      {headlines?.length ? (
        <ul className="mt-4 space-y-3">
          {headlines.map((headline) => (
            <li key={headline.url}>
              <a
                className="text-sm font-medium underline underline-offset-4 hover:text-gold-light"
                href={headline.url}
                target="_blank"
                rel="noreferrer"
              >
                {headline.title}
              </a>
              <p className="text-xs text-text-3">
                {headline.publisher && `${headline.publisher} · `}
                <time dateTime={headline.date}>{headline.date}</time>
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-text-2">
          {headlines
            ? "No related headlines found for this snapshot."
            : "News is unavailable for this snapshot."}
        </p>
      )}
    </Panel>
  );
}

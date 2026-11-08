/** Small YES-price line for Lobby cards: [unix seconds, price 0–1] points up to the snapshot. */
export function Sparkline({
  points,
  width = 120,
  height = 36,
}: {
  points: [number, number][];
  width?: number;
  height?: number;
}) {
  if (points.length < 2) return null;
  const t0 = points[0]![0];
  const t1 = points[points.length - 1]![0];
  const x = (t: number) => (t1 === t0 ? width : ((t - t0) / (t1 - t0)) * width);
  const y = (p: number) => height - 2 - p * (height - 4);
  const d = points
    .map(([t, p], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${y(p).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
      className="overflow-visible"
    >
      <line
        x1="0"
        x2={width}
        y1={y(0.5)}
        y2={y(0.5)}
        stroke="var(--border)"
        strokeDasharray="2 3"
      />
      <path
        d={d}
        fill="none"
        stroke="var(--gold)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={x(t1)} cy={y(points[points.length - 1]![1])} r="2.5" fill="var(--gold-light)" />
    </svg>
  );
}

/** Items per minute over the last hour as an inline SVG polyline (no chart library needed). */
export function Sparkline({ values }: { values: readonly number[] }) {
  const width = 120;
  const height = 24;
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values
    .map((value, index) => `${(index * step).toFixed(1)},${(height - 1 - (value / max) * (height - 2)).toFixed(1)}`)
    .join(" ");
  return (
    <svg
      role="img"
      aria-label="Throughput last 60 minutes"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="h-6 w-full text-brand-hi"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

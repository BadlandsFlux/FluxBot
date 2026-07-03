export default function BarChart({ data, height = 120, formatLabel }) {
  if (!data.length) return null;
  const max = Math.max(...data.map((d) => d.value), 1);
  const barWidth = 100 / data.length;

  return (
    <div className="bar-chart" style={{ height }}>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="bar-chart-svg">
        {data.map((d, i) => {
          const barHeight = (d.value / max) * (height - 20);
          const x = i * barWidth;
          return (
            <g key={i}>
              <rect
                x={x + barWidth * 0.15}
                y={height - 20 - barHeight}
                width={barWidth * 0.7}
                height={Math.max(barHeight, d.value > 0 ? 2 : 0)}
                rx="1.5"
                className="bar-chart-bar"
              >
                <title>{`${formatLabel ? formatLabel(d.label) : d.label}: ${d.value}`}</title>
              </rect>
            </g>
          );
        })}
      </svg>
      <div className="bar-chart-labels">
        {data.map((d, i) => (
          <span key={i} title={formatLabel ? formatLabel(d.label) : d.label}>
            {i === 0 || i === data.length - 1 || data.length <= 7 ? (formatLabel ? formatLabel(d.label) : d.label) : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

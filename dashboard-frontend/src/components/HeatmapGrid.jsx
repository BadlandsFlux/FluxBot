const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]; // index matches Postgres EXTRACT(DOW) and JS Date#getDay()

export default function HeatmapGrid({ data }) {
  const byKey = Object.fromEntries(data.map((d) => [`${d.day}-${d.hour}`, d.count]));
  const max = Math.max(1, ...data.map((d) => d.count));

  return (
    <div className="heatmap">
      <div className="heatmap-hours">
        <div className="heatmap-corner" />
        {Array.from({ length: 24 }, (_, h) => (
          <div className="heatmap-hour-label" key={h}>
            {h % 4 === 0 ? h : ""}
          </div>
        ))}
      </div>
      {DAY_LABELS.map((label, day) => (
        <div className="heatmap-row" key={day}>
          <div className="heatmap-day-label">{label}</div>
          {Array.from({ length: 24 }, (_, hour) => {
            const count = byKey[`${day}-${hour}`] || 0;
            const intensity = count / max;
            return (
              <div
                key={hour}
                className={`heatmap-cell ${count === 0 ? "empty" : ""}`}
                style={count > 0 ? { opacity: 0.15 + intensity * 0.85 } : undefined}
                title={`${label} ${hour}:00, ${count} message${count !== 1 ? "s" : ""}`}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}

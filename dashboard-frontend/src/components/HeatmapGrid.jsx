const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]; // index matches Postgres EXTRACT(DOW) and JS Date#getDay()

// The backend always buckets in UTC (see common/db.py's record_message_activity),
// so cells are re-keyed here to whichever (day, hour) bucket that UTC slot
// falls into in the viewer's own local time, rather than labeling hours 0-23
// as "UTC" and making everyone do the math themselves. Rounded to the
// nearest whole hour: the data is only ever hour-granular to begin with, so
// a half-hour-offset timezone (e.g. UTC+5:30) losing that last bit of
// precision isn't a new limitation, just the existing one carried over.
const LOCAL_OFFSET_HOURS = Math.round(-new Date().getTimezoneOffset() / 60);

function toLocalBucket(day, hour) {
  const total = day * 24 + hour + LOCAL_OFFSET_HOURS;
  const localDay = (((Math.floor(total / 24)) % 7) + 7) % 7;
  const localHour = ((total % 24) + 24) % 24;
  return `${localDay}-${localHour}`;
}

export default function HeatmapGrid({ data }) {
  const byKey = Object.fromEntries(data.map((d) => [toLocalBucket(d.day, d.hour), d.count]));
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

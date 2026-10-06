function fmtTimestamp() {
  return new Date().toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// Staff-entered text ending up as a literal href/src is exactly the shape
// CodeQL's "DOM text reinterpreted as HTML" check looks for: a javascript:
// URL here would run in this authenticated dashboard session the moment
// another staff member views the preview or clicks the linked title, no
// server round-trip needed. Only ever hand the DOM a value we've confirmed
// is an actual http(s) URL, never the raw field.
function safeUrl(raw) {
  const trimmed = (raw || "").trim();
  if (!trimmed) return "";
  try {
    const parsed = new URL(trimmed);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? trimmed : "";
  } catch {
    return "";
  }
}

export default function EmbedPreview({
  title, description, color, url, imageUrl, thumbnailUrl, footer,
  authorName, authorIconUrl, timestamp, fields = [],
}) {
  const hasContent =
    title?.trim() || description?.trim() || imageUrl?.trim() || footer?.trim() ||
    authorName?.trim() || fields.some((f) => f.name?.trim() || f.value?.trim());

  if (!hasContent) {
    return (
      <div className="embed-preview embed-preview-empty">
        <p className="muted small">Fill in the fields to see a preview of the embed here.</p>
      </div>
    );
  }

  const footerLine = [footer?.trim(), timestamp ? fmtTimestamp() : ""].filter(Boolean).join(" • ");

  return (
    <div className="embed-preview">
      <div className="embed-preview-card" style={{ borderLeftColor: color || "#5865f2" }}>
        {safeUrl(thumbnailUrl) && (
          <img
            src={safeUrl(thumbnailUrl)}
            alt=""
            className="embed-preview-thumbnail"
            onError={(e) => { e.target.style.display = "none"; }}
          />
        )}
        {authorName?.trim() && (
          <div className="embed-preview-author">
            {safeUrl(authorIconUrl) && (
              <img
                src={safeUrl(authorIconUrl)}
                alt=""
                className="embed-preview-author-icon"
                onError={(e) => { e.target.style.display = "none"; }}
              />
            )}
            {authorName}
          </div>
        )}
        {title?.trim() && (
          <div className="embed-preview-title">
            {safeUrl(url) ? <a href={safeUrl(url)} target="_blank" rel="noreferrer">{title}</a> : title}
          </div>
        )}
        {description?.trim() && <div className="embed-preview-description">{description}</div>}
        {fields.some((f) => f.name?.trim() || f.value?.trim()) && (
          <div className="embed-preview-fields">
            {fields.filter((f) => f.name?.trim() || f.value?.trim()).map((f, i) => (
              <div className={`embed-preview-field ${f.inline ? "embed-preview-field-inline" : ""}`} key={i}>
                <div className="embed-preview-field-name">{f.name}</div>
                <div className="embed-preview-field-value">{f.value}</div>
              </div>
            ))}
          </div>
        )}
        {safeUrl(imageUrl) && (
          <img
            src={safeUrl(imageUrl)}
            alt=""
            className="embed-preview-image"
            onError={(e) => { e.target.style.display = "none"; }}
          />
        )}
        {footerLine && <div className="embed-preview-footer">{footerLine}</div>}
      </div>
    </div>
  );
}

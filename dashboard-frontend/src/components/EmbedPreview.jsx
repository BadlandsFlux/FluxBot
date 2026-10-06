function fmtTimestamp() {
  return new Date().toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric" });
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
        {thumbnailUrl?.trim() && (
          <img
            src={thumbnailUrl}
            alt=""
            className="embed-preview-thumbnail"
            onError={(e) => { e.target.style.display = "none"; }}
          />
        )}
        {authorName?.trim() && (
          <div className="embed-preview-author">
            {authorIconUrl?.trim() && (
              <img
                src={authorIconUrl}
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
            {url?.trim() ? <a href={url} target="_blank" rel="noreferrer">{title}</a> : title}
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
        {imageUrl?.trim() && (
          <img
            src={imageUrl}
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

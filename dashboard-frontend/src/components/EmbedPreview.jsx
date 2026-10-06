function fmtTimestamp() {
  return new Date().toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const HTTP_URL_RE = /^https?:\/\//i;

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

  // Staff-entered text ending up as a literal href/src is exactly the shape
  // CodeQL's "DOM text reinterpreted as HTML" check looks for: a javascript:
  // URL here would run in this authenticated dashboard session the moment
  // another staff member views the preview or clicks the linked title, no
  // server round-trip needed. Each guard below tests the exact value it
  // then hands to the sink, in this same scope, rather than through a
  // helper function, so it's actually recognized as a sanitizing check
  // rather than dead weight the taint tracker sees straight through.
  const trimmedImageUrl = (imageUrl || "").trim();
  const safeImageUrl = HTTP_URL_RE.test(trimmedImageUrl) ? trimmedImageUrl : "";
  const trimmedThumbnailUrl = (thumbnailUrl || "").trim();
  const safeThumbnailUrl = HTTP_URL_RE.test(trimmedThumbnailUrl) ? trimmedThumbnailUrl : "";
  const trimmedAuthorIconUrl = (authorIconUrl || "").trim();
  const safeAuthorIconUrl = HTTP_URL_RE.test(trimmedAuthorIconUrl) ? trimmedAuthorIconUrl : "";
  const trimmedTitleUrl = (url || "").trim();
  const safeTitleUrl = HTTP_URL_RE.test(trimmedTitleUrl) ? trimmedTitleUrl : "";

  return (
    <div className="embed-preview">
      <div className="embed-preview-card" style={{ borderLeftColor: color || "#5865f2" }}>
        {safeThumbnailUrl && (
          <img
            src={safeThumbnailUrl}
            alt=""
            className="embed-preview-thumbnail"
            onError={(e) => { e.target.style.display = "none"; }}
          />
        )}
        {authorName?.trim() && (
          <div className="embed-preview-author">
            {safeAuthorIconUrl && (
              <img
                src={safeAuthorIconUrl}
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
            {safeTitleUrl ? <a href={safeTitleUrl} target="_blank" rel="noreferrer">{title}</a> : title}
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
        {safeImageUrl && (
          <img
            src={safeImageUrl}
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

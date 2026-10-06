function fmtTimestamp() {
  return new Date().toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const HTTP_URL_RE = /^https?:\/\//i;

// A small, good-enough approximation of the markdown subset the toolbar
// writes (headers, bold/italic/underline/strike, spoiler, inline code,
// bullet/numbered lists, quotes), so the preview actually looks like the
// formatted embed Fluxer will render instead of showing raw "**text**".
// Not a general-purpose markdown parser, just covers what this editor
// produces, plus the handful of marks someone might type by hand.
const INLINE_RE = /\*\*\*(.+?)\*\*\*|\*\*(.+?)\*\*|__(.+?)__|~~(.+?)~~|\|\|(.+?)\|\||\*(.+?)\*|_(.+?)_|`([^`]+?)`/;

function parseInline(text) {
  if (!text) return null;
  const match = INLINE_RE.exec(text);
  if (!match) return text;
  const before = text.slice(0, match.index);
  const after = text.slice(match.index + match[0].length);
  let node;
  if (match[1] !== undefined) node = <strong><em>{parseInline(match[1])}</em></strong>;
  else if (match[2] !== undefined) node = <strong>{parseInline(match[2])}</strong>;
  else if (match[3] !== undefined) node = <u>{parseInline(match[3])}</u>;
  else if (match[4] !== undefined) node = <s>{parseInline(match[4])}</s>;
  else if (match[5] !== undefined) node = <span className="embed-md-spoiler">{parseInline(match[5])}</span>;
  else if (match[6] !== undefined) node = <em>{parseInline(match[6])}</em>;
  else if (match[7] !== undefined) node = <em>{parseInline(match[7])}</em>;
  else node = <code>{match[8]}</code>;
  return (
    <>
      {before}
      {node}
      {parseInline(after)}
    </>
  );
}

function renderMarkdownLine(line, key) {
  let m;
  if ((m = /^### (.*)$/.exec(line))) return <div key={key} className="embed-md-h3">{parseInline(m[1])}</div>;
  if ((m = /^## (.*)$/.exec(line))) return <div key={key} className="embed-md-h2">{parseInline(m[1])}</div>;
  if ((m = /^# (.*)$/.exec(line))) return <div key={key} className="embed-md-h1">{parseInline(m[1])}</div>;
  if ((m = /^>\s?(.*)$/.exec(line))) return <div key={key} className="embed-md-quote">{parseInline(m[1])}</div>;
  if ((m = /^[-*]\s+(.*)$/.exec(line))) return <div key={key} className="embed-md-li">• {parseInline(m[1])}</div>;
  if ((m = /^(\d+)\.\s+(.*)$/.exec(line))) {
    return <div key={key} className="embed-md-li">{m[1]}. {parseInline(m[2])}</div>;
  }
  if (!line.trim()) return <div key={key} className="embed-md-blank">&nbsp;</div>;
  return <div key={key}>{parseInline(line)}</div>;
}

function renderMarkdown(text) {
  return (text || "").split("\n").map((line, i) => renderMarkdownLine(line, i));
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
        {description?.trim() && <div className="embed-preview-description">{renderMarkdown(description)}</div>}
        {fields.some((f) => f.name?.trim() || f.value?.trim()) && (
          <div className="embed-preview-fields">
            {fields.filter((f) => f.name?.trim() || f.value?.trim()).map((f, i) => (
              <div className={`embed-preview-field ${f.inline ? "embed-preview-field-inline" : ""}`} key={i}>
                <div className="embed-preview-field-name">{f.name}</div>
                <div className="embed-preview-field-value">{renderMarkdown(f.value)}</div>
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

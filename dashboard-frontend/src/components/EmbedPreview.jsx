export default function EmbedPreview({ title, description, color, imageUrl, footer }) {
  const hasContent = title?.trim() || description?.trim() || imageUrl?.trim() || footer?.trim();

  if (!hasContent) {
    return (
      <div className="embed-preview embed-preview-empty">
        <p className="muted small">Fill in the fields to see a preview of the embed here.</p>
      </div>
    );
  }

  return (
    <div className="embed-preview">
      <div className="embed-preview-card" style={{ borderLeftColor: color || "#5865f2" }}>
        {title?.trim() && <div className="embed-preview-title">{title}</div>}
        {description?.trim() && <div className="embed-preview-description">{description}</div>}
        {imageUrl?.trim() && (
          <img
            src={imageUrl}
            alt=""
            className="embed-preview-image"
            onError={(e) => {
              e.target.style.display = "none";
            }}
          />
        )}
        {footer?.trim() && <div className="embed-preview-footer">{footer}</div>}
      </div>
    </div>
  );
}

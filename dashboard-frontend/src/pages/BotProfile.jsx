import { useEffect, useRef, useState } from "react";
import { Bot, Upload } from "lucide-react";
import { api } from "../api";
import { useFlash } from "../components/Flash";
import Spinner from "../components/Spinner";

export default function BotProfile() {
  const flash = useFlash();
  const fileRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [uploading, setUploading] = useState(false);

  function handlePick(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setPreview(URL.createObjectURL(file));
  }

  // Each createObjectURL() call holds a reference until explicitly revoked,
  // without this, picking several files in a row (or leaving the page open)
  // leaks memory. Runs before setting a new preview and on unmount, so the
  // previous blob URL is always cleaned up, not just the last one.
  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview);
    };
  }, [preview]);

  async function handleUpload(e) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      flash("Pick an image first.", "error");
      return;
    }
    setUploading(true);
    try {
      const result = await api.setBotAvatar(file);
      if (result.fluxer_updated) {
        flash("Updated the bot's Fluxer avatar and the dashboard favicon. You may need a hard refresh to see the favicon change in your tab.");
      } else {
        flash(
          `Dashboard favicon updated. Couldn't update the bot's Fluxer avatar automatically: ${result.fluxer_error || "unknown error"}. ` +
          "You can set that manually from Fluxer's Bot Application page instead.",
          "error",
        );
      }
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="card bot-profile-card">
      <h2>
        <Bot size={18} /> Bot profile
      </h2>
      <p className="muted small">
        Owner-only. Updates the dashboard's own favicon right away, and tries to update the bot's avatar on
        Fluxer too, though that part isn't guaranteed to work on every instance right now, in which case set it
        manually from Fluxer's Bot Application page. PNG, JPEG, or WEBP, 8 MiB max.
      </p>

      <form onSubmit={handleUpload} className="bot-profile-form">
        <div className="bot-profile-preview">
          {preview ? <img src={preview} alt="Preview" /> : <div className="bot-profile-preview-empty">?</div>}
        </div>
        <div className="bot-profile-controls">
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={handlePick} />
          <button className="btn btn-primary btn-small" type="submit" disabled={uploading}>
            {uploading ? <Spinner size={14} /> : <Upload size={14} />}
            {uploading ? "Uploading…" : "Set as bot avatar"}
          </button>
        </div>
      </form>
    </div>
  );
}

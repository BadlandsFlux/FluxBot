import { useRef, useState } from "react";
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

  async function handleUpload(e) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      flash("Pick an image first.", "error");
      return;
    }
    setUploading(true);
    try {
      await api.setBotAvatar(file);
      flash("Updated. This also changed the favicon, you may need a hard refresh to see it in your tab.");
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
        Owner-only. Changes the bot's avatar on Fluxer and the dashboard's favicon, both from the same image.
        PNG, JPEG, or WEBP, 8 MiB max.
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

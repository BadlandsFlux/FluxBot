import { useState } from "react";
import { Send } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";
import Combobox from "./Combobox";
import EmbedPreview from "./EmbedPreview";

export default function AnnouncementBuilder({ guildId, channels }) {
  const flash = useFlash();
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#5865f2");
  const [imageUrl, setImageUrl] = useState("");
  const [footer, setFooter] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!channelId || (!title.trim() && !description.trim())) {
      flash("Pick a channel and give at least a title or description.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await api.announce(guildId, {
        channel_id: channelId,
        title: title.trim(),
        description: description.trim(),
        color: color.replace("#", ""),
        image_url: imageUrl.trim(),
        footer: footer.trim(),
      });
      flash("Announcement sent.");
      setTitle("");
      setDescription("");
      setImageUrl("");
      setFooter("");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="settings-form">
      <label>
        Channel
        <Combobox options={channels} value={channelId} onChange={setChannelId} placeholder="Pick a channel" />
      </label>
      <div className="form-row form-row-title-color">
        <label>
          Title
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Big announcement" />
        </label>
        <label>
          Color
          <input type="color" className="color-input" value={color} onChange={(e) => setColor(e.target.value)} />
        </label>
      </div>
      <label>
        Description
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Write the announcement here..."
          rows={4}
        />
      </label>
      <label>
        Image URL (optional)
        <input type="text" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://..." />
      </label>
      <label>
        Footer (optional)
        <input type="text" value={footer} onChange={(e) => setFooter(e.target.value)} placeholder="The team" />
      </label>
      <EmbedPreview title={title} description={description} color={color} imageUrl={imageUrl} footer={footer} />
      <div className="form-spacer" />
      <button className="btn btn-primary" type="submit" disabled={submitting}>
        {submitting ? <Spinner size={14} /> : <Send size={14} />}
        {submitting ? "Sending…" : "Send announcement"}
      </button>
    </form>
  );
}

import { useRef, useState } from "react";
import { Plus, Send, X } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";
import Combobox from "./Combobox";
import MarkdownToolbar, { handleListContinue } from "./MarkdownToolbar";
import EmbedPreview from "./EmbedPreview";

const MAX_FIELDS = 25;

function FieldRow({ field, onChange, onRemove }) {
  const valueRef = useRef(null);
  return (
    <div className="embed-field-row">
      <div className="embed-field-row-head">
        <input
          type="text"
          value={field.name}
          onChange={(e) => onChange({ ...field, name: e.target.value })}
          placeholder="Field name"
          maxLength={256}
          aria-label="Field name"
        />
        <label className="embed-field-inline-toggle">
          <input
            type="checkbox"
            checked={field.inline}
            onChange={(e) => onChange({ ...field, inline: e.target.checked })}
          />
          Inline
        </label>
        <button type="button" className="btn btn-ghost btn-small" onClick={onRemove} aria-label="Remove field">
          <X size={14} />
        </button>
      </div>
      <MarkdownToolbar textareaRef={valueRef} value={field.value} onChange={(v) => onChange({ ...field, value: v })} />
      <textarea
        ref={valueRef}
        value={field.value}
        onChange={(e) => onChange({ ...field, value: e.target.value })}
        onKeyDown={(e) => handleListContinue(e, field.value, (v) => onChange({ ...field, value: v }))}
        placeholder="Field value"
        rows={4}
        maxLength={1024}
      />
    </div>
  );
}

export default function EmbedBuilder({ guildId, channels }) {
  const flash = useFlash();
  const descRef = useRef(null);
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#5865f2");
  const [imageUrl, setImageUrl] = useState("");
  const [thumbnailUrl, setThumbnailUrl] = useState("");
  const [footer, setFooter] = useState("");
  const [authorName, setAuthorName] = useState("");
  const [authorIconUrl, setAuthorIconUrl] = useState("");
  const [authorUrl, setAuthorUrl] = useState("");
  const [timestamp, setTimestamp] = useState(false);
  const [fields, setFields] = useState([]);
  const [submitting, setSubmitting] = useState(false);

  function addField() {
    if (fields.length >= MAX_FIELDS) return;
    setFields((f) => [...f, { name: "", value: "", inline: false }]);
  }

  function updateField(i, next) {
    setFields((f) => f.map((field, idx) => (idx === i ? next : field)));
  }

  function removeField(i) {
    setFields((f) => f.filter((_, idx) => idx !== i));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!channelId || (!title.trim() && !description.trim())) {
      flash("Pick a channel and give at least a title or description.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await api.sendEmbed(guildId, {
        channel_id: channelId,
        title: title.trim(),
        url: url.trim(),
        description: description.trim(),
        color: color.replace("#", ""),
        image_url: imageUrl.trim(),
        thumbnail_url: thumbnailUrl.trim(),
        footer: footer.trim(),
        author_name: authorName.trim(),
        author_icon_url: authorIconUrl.trim(),
        author_url: authorUrl.trim(),
        timestamp,
        fields: fields.map((f) => ({ name: f.name.trim(), value: f.value.trim(), inline: f.inline })),
      });
      flash("Embed sent.");
      setTitle("");
      setUrl("");
      setDescription("");
      setImageUrl("");
      setThumbnailUrl("");
      setFooter("");
      setAuthorName("");
      setAuthorIconUrl("");
      setAuthorUrl("");
      setTimestamp(false);
      setFields([]);
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

      <div className="form-row form-row-3">
        <label>
          Author name (optional)
          <input type="text" value={authorName} onChange={(e) => setAuthorName(e.target.value)} placeholder="Staff team" maxLength={256} />
        </label>
        <label>
          Author icon URL (optional)
          <input type="text" value={authorIconUrl} onChange={(e) => setAuthorIconUrl(e.target.value)} placeholder="https://..." />
        </label>
        <label>
          Author link (optional)
          <input type="text" value={authorUrl} onChange={(e) => setAuthorUrl(e.target.value)} placeholder="https://..." />
        </label>
      </div>

      <div className="form-row form-row-title-color">
        <label>
          Title
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Embed title" maxLength={256} />
        </label>
        <label>
          Color
          <input type="color" className="color-input" value={color} onChange={(e) => setColor(e.target.value)} />
        </label>
      </div>
      <label>
        Title link (optional)
        <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://... (makes the title clickable)" />
      </label>

      <label>
        Description
        <MarkdownToolbar textareaRef={descRef} value={description} onChange={setDescription} />
        <textarea
          ref={descRef}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => handleListContinue(e, description, setDescription)}
          placeholder="Write the embed here..."
          rows={8}
          maxLength={4096}
        />
      </label>

      <div className="embed-fields-section">
        <div className="embed-fields-head">
          <span>Fields (optional)</span>
          <button type="button" className="btn btn-ghost btn-small" onClick={addField} disabled={fields.length >= MAX_FIELDS}>
            <Plus size={14} /> Add field
          </button>
        </div>
        {fields.map((f, i) => (
          <FieldRow key={i} field={f} onChange={(next) => updateField(i, next)} onRemove={() => removeField(i)} />
        ))}
      </div>

      <div className="form-row form-row-3">
        <label>
          Image URL (optional)
          <input type="text" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://..." />
        </label>
        <label>
          Thumbnail URL (optional)
          <input type="text" value={thumbnailUrl} onChange={(e) => setThumbnailUrl(e.target.value)} placeholder="https://..." />
        </label>
        <label>
          Footer (optional)
          <input type="text" value={footer} onChange={(e) => setFooter(e.target.value)} placeholder="The team" maxLength={2048} />
        </label>
      </div>

      <label className="embed-timestamp-toggle">
        <input type="checkbox" checked={timestamp} onChange={(e) => setTimestamp(e.target.checked)} />
        Add current timestamp
      </label>

      <EmbedPreview
        title={title} description={description} color={color} url={url} imageUrl={imageUrl}
        thumbnailUrl={thumbnailUrl} footer={footer} authorName={authorName} authorIconUrl={authorIconUrl}
        timestamp={timestamp} fields={fields}
      />
      <div className="form-spacer" />
      <button className="btn btn-primary" type="submit" disabled={submitting}>
        {submitting ? <Spinner size={14} /> : <Send size={14} />}
        {submitting ? "Sending…" : "Send embed"}
      </button>
    </form>
  );
}

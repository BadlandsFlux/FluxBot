import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Download, GripVertical, Plus, Send, Upload, X } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";
import Combobox from "./Combobox";
import MarkdownToolbar, { handleListContinue } from "./MarkdownToolbar";
import EmbedPreview from "./EmbedPreview";
import EmojiInsertButton from "./EmojiInsertButton";

const MAX_FIELDS = 25;

// Fluxer's channel type enum (Discord-compatible); only the ones the
// embed picker ever needs to tell apart.
const CHANNEL_TYPE_FORUM = 15;
const CHANNEL_TYPE_MEDIA = 16;
const POST_ONLY_CHANNEL_TYPES = new Set([CHANNEL_TYPE_FORUM, CHANNEL_TYPE_MEDIA]);
const CHANNEL_TYPE_SUFFIX = { 5: " (announcement)", [CHANNEL_TYPE_FORUM]: " (forum)", [CHANNEL_TYPE_MEDIA]: " (media)" };

function FieldRow({ field, index, count, onChange, onRemove, onMove, dragState, guildId }) {
  const valueRef = useRef(null);
  const { draggedId, setDraggedId, overId, setOverId } = dragState;
  const isDragging = draggedId === field.id;
  const isDropTarget = overId === field.id && draggedId !== null && draggedId !== field.id;

  return (
    <div
      className={`embed-field-row${isDragging ? " embed-field-row-dragging" : ""}${isDropTarget ? " embed-field-row-drop-target" : ""}`}
      onDragOver={(e) => {
        if (draggedId === null) return;
        e.preventDefault();
        setOverId(field.id);
      }}
      onDrop={(e) => {
        e.preventDefault();
        if (draggedId !== null) onMove(draggedId, field.id);
        setDraggedId(null);
        setOverId(null);
      }}
    >
      <div className="embed-field-row-head">
        <div
          className="embed-field-drag-handle"
          draggable
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = "move";
            setDraggedId(field.id);
          }}
          onDragEnd={() => {
            setDraggedId(null);
            setOverId(null);
          }}
          title="Drag to reorder"
          aria-label="Drag to reorder this field"
        >
          <GripVertical size={14} />
        </div>
        <div className="embed-field-reorder-buttons">
          <button type="button" className="btn btn-ghost btn-small" onClick={() => onMove(field.id, "up")}
                  disabled={index === 0} aria-label="Move field up" title="Move up">
            <ChevronUp size={12} />
          </button>
          <button type="button" className="btn btn-ghost btn-small" onClick={() => onMove(field.id, "down")}
                  disabled={index === count - 1} aria-label="Move field down" title="Move down">
            <ChevronDown size={12} />
          </button>
        </div>
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
      <MarkdownToolbar textareaRef={valueRef} value={field.value} onChange={(v) => onChange({ ...field, value: v })}
                       guildId={guildId} />
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

// Everything but channelId: the channel is specific to the server you're
// in, but the rest of an embed (what this export/import pair exists for)
// is exactly the part worth reusing in a different one.
function buildExport({ title, url, description, color, imageUrl, thumbnailUrl, footer,
                        authorName, authorIconUrl, authorUrl, timestamp, fields }) {
  return {
    kind: "fluxbot-embed", version: 1,
    title, url, description, color, imageUrl, thumbnailUrl, footer,
    authorName, authorIconUrl, authorUrl, timestamp,
    fields: fields.map((f) => ({ name: f.name, value: f.value, inline: !!f.inline })),
  };
}

function slugForFilename(title) {
  const slug = (title || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug ? `embed-${slug}` : "embed";
}

export default function EmbedBuilder({ guildId }) {
  const flash = useFlash();
  const descRef = useRef(null);
  const titleRef = useRef(null);
  const footerRef = useRef(null);
  const authorNameRef = useRef(null);
  const importInputRef = useRef(null);
  // Its own channel fetch, separate from the rest of the Settings tab's
  // pickers (useRolesChannels): this is the one place in the dashboard
  // that can actually post into a forum/media channel (via a named
  // thread/post, see api_send_embed's include_posts branch), so it's
  // the one picker that needs those included.
  const [channels, setChannels] = useState([]);
  const [channelId, setChannelId] = useState("");
  const [postTitle, setPostTitle] = useState("");
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
  // A stable id per field row, independent of its position in the array:
  // keying FieldRow by array index instead would make React reassign an
  // existing <textarea> (and whatever the user was mid-typing in it, and
  // its focus) to a different field's data whenever a field before it is
  // removed.
  const nextFieldId = useRef(0);
  const [draggedId, setDraggedId] = useState(null);
  const [overId, setOverId] = useState(null);
  const dragState = { draggedId, setDraggedId, overId, setOverId };

  useEffect(() => {
    let cancelled = false;
    api.embedChannels(guildId)
      .then((res) => !cancelled && setChannels(res.channels))
      .catch(() => !cancelled && setChannels([]));
    return () => {
      cancelled = true;
    };
  }, [guildId]);

  const channelOptions = channels.map((c) => ({
    ...c,
    name: `${c.name}${CHANNEL_TYPE_SUFFIX[c.type] || ""}`,
  }));
  const selectedChannel = channels.find((c) => c.id === channelId);
  const postingToForum = !!selectedChannel && POST_ONLY_CHANNEL_TYPES.has(selectedChannel.type);

  function addField() {
    if (fields.length >= MAX_FIELDS) return;
    nextFieldId.current += 1;
    setFields((f) => [...f, { id: nextFieldId.current, name: "", value: "", inline: false }]);
  }

  function updateField(id, next) {
    setFields((f) => f.map((field) => (field.id === id ? next : field)));
  }

  function removeField(id) {
    setFields((f) => f.filter((field) => field.id !== id));
  }

  // `target` is either another field's id (drag-and-drop landed on it) or
  // the literal string "up"/"down" (the arrow buttons move by one slot).
  function moveField(id, target) {
    setFields((f) => {
      const fromIndex = f.findIndex((field) => field.id === id);
      if (fromIndex === -1) return f;
      let toIndex;
      if (target === "up") toIndex = fromIndex - 1;
      else if (target === "down") toIndex = fromIndex + 1;
      else toIndex = f.findIndex((field) => field.id === target);
      if (toIndex === -1 || toIndex >= f.length || toIndex === fromIndex) return f;
      const next = [...f];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }

  function exportToFile() {
    const data = buildExport({
      title, url, description, color, imageUrl, thumbnailUrl, footer,
      authorName, authorIconUrl, authorUrl, timestamp, fields,
    });
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = `${slugForFilename(title)}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  }

  function triggerImport() {
    importInputRef.current?.click();
  }

  async function handleImportFile(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // so picking the same file again still fires onChange
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      if (typeof data !== "object" || data === null || Array.isArray(data)) {
        throw new Error("not an embed file");
      }
      setTitle(typeof data.title === "string" ? data.title : "");
      setUrl(typeof data.url === "string" ? data.url : "");
      setDescription(typeof data.description === "string" ? data.description : "");
      setColor(typeof data.color === "string" && /^#[0-9a-fA-F]{6}$/.test(data.color) ? data.color : "#5865f2");
      setImageUrl(typeof data.imageUrl === "string" ? data.imageUrl : "");
      setThumbnailUrl(typeof data.thumbnailUrl === "string" ? data.thumbnailUrl : "");
      setFooter(typeof data.footer === "string" ? data.footer : "");
      setAuthorName(typeof data.authorName === "string" ? data.authorName : "");
      setAuthorIconUrl(typeof data.authorIconUrl === "string" ? data.authorIconUrl : "");
      setAuthorUrl(typeof data.authorUrl === "string" ? data.authorUrl : "");
      setTimestamp(!!data.timestamp);
      const importedFields = Array.isArray(data.fields) ? data.fields : [];
      setFields(
        importedFields.slice(0, MAX_FIELDS).map((f) => {
          nextFieldId.current += 1;
          return {
            id: nextFieldId.current,
            name: typeof f?.name === "string" ? f.name : "",
            value: typeof f?.value === "string" ? f.value : "",
            inline: !!f?.inline,
          };
        }),
      );
      flash("Embed imported. Pick a channel and send whenever you're ready.");
    } catch {
      flash("Couldn't read that file as an embed export.", "error");
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!channelId || (!title.trim() && !description.trim())) {
      flash("Pick a channel and give at least a title or description.", "error");
      return;
    }
    if (postingToForum && !postTitle.trim()) {
      flash("That's a forum/media channel, give the post a title.", "error");
      return;
    }
    setSubmitting(true);
    try {
      await api.sendEmbed(guildId, {
        channel_id: channelId,
        post_title: postTitle.trim(),
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
      setPostTitle("");
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
      <div className="embed-builder-toolbar">
        <button type="button" className="btn btn-ghost btn-small" onClick={exportToFile}>
          <Download size={14} /> Export to file
        </button>
        <button type="button" className="btn btn-ghost btn-small" onClick={triggerImport}>
          <Upload size={14} /> Import from file
        </button>
        <input ref={importInputRef} type="file" accept=".json,application/json" onChange={handleImportFile}
               style={{ display: "none" }} aria-hidden="true" tabIndex={-1} />
        <span className="muted small">Exports everything but the channel, so you can bring an embed into any server.</span>
      </div>

      <label>
        Channel
        <Combobox options={channelOptions} value={channelId} onChange={setChannelId} placeholder="Pick a channel" />
      </label>
      {postingToForum && (
        <label>
          Post title
          <input type="text" value={postTitle} onChange={(e) => setPostTitle(e.target.value)}
                 placeholder="Title for the new forum post" maxLength={100} />
          <p className="muted small">
            Forum/media channels don't take a plain message, each send here starts a new post.
          </p>
        </label>
      )}

      <div className="form-row form-row-3">
        <label>
          Author name (optional)
          <div className="input-with-emoji">
            <input ref={authorNameRef} type="text" value={authorName} onChange={(e) => setAuthorName(e.target.value)}
                   placeholder="Staff team" maxLength={256} />
            <EmojiInsertButton targetRef={authorNameRef} value={authorName} onChange={setAuthorName} guildId={guildId} />
          </div>
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
          <div className="input-with-emoji">
            <input ref={titleRef} type="text" value={title} onChange={(e) => setTitle(e.target.value)}
                   placeholder="Embed title" maxLength={256} />
            <EmojiInsertButton targetRef={titleRef} value={title} onChange={setTitle} guildId={guildId} />
          </div>
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
        <MarkdownToolbar textareaRef={descRef} value={description} onChange={setDescription} guildId={guildId} />
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
          <FieldRow key={f.id} field={f} index={i} count={fields.length} onChange={(next) => updateField(f.id, next)}
                    onRemove={() => removeField(f.id)} onMove={moveField} dragState={dragState} guildId={guildId} />
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
          <div className="input-with-emoji">
            <input ref={footerRef} type="text" value={footer} onChange={(e) => setFooter(e.target.value)}
                   placeholder="The team" maxLength={2048} />
            <EmojiInsertButton targetRef={footerRef} value={footer} onChange={setFooter} guildId={guildId} />
          </div>
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

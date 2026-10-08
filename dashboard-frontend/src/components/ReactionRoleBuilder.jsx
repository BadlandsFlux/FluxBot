import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";
import Combobox from "./Combobox";
import EmojiPicker from "./EmojiPicker";
import EmbedPreview from "./EmbedPreview";

const BLANK_ROW = { emoji: "", label: "", role_id: "" };

function emptyState() {
  return { channelId: "", title: "Pick your roles", description: "", color: "#5865f2", rows: [{ ...BLANK_ROW }] };
}

// `editing` (null in create mode) is the message group being edited, as
// ReactionRolesTab builds it: { message_id, channel_id, title,
// description, color, entries: [{emoji, label, role_id}] }.
export default function ReactionRoleBuilder({ guildId, roles, channels, onCreated, editing, onCancelEdit }) {
  const flash = useFlash();
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("Pick your roles");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#5865f2");
  const [rows, setRows] = useState([{ ...BLANK_ROW }]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (editing) {
      setChannelId(editing.channel_id);
      setTitle(editing.title || "Pick your roles");
      setDescription(editing.description || "");
      // editing.color == null (not just falsy): 0 is a real, valid color
      // (pure black) and must not fall through to the default blue.
      setColor(editing.color != null ? `#${editing.color.toString(16).padStart(6, "0")}` : "#5865f2");
      setRows(
        editing.entries.length
          ? editing.entries.map((e) => ({ emoji: e.emoji, label: e.label, role_id: e.role_id }))
          : [{ ...BLANK_ROW }]
      );
    } else {
      const blank = emptyState();
      setChannelId(blank.channelId);
      setTitle(blank.title);
      setDescription(blank.description);
      setColor(blank.color);
      setRows(blank.rows);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: see below
  }, [editing?.message_id]);

  function updateRow(index, field, value) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, { ...BLANK_ROW }]);
  }

  function removeRow(index) {
    setRows((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev));
  }

  const channelNameById = Object.fromEntries(channels.map((c) => [c.id, c.name]));
  const previewLines = rows
    .filter((r) => r.emoji && r.role_id)
    .map((r) => (r.label ? `${r.emoji} **${r.label}**` : r.emoji));
  const previewDescription = [description, previewLines.join("\n")].filter(Boolean).join("\n\n");

  async function handleSubmit(e) {
    e.preventDefault();
    const pairs = rows.filter((r) => r.emoji && r.role_id);
    if ((!editing && !channelId) || pairs.length === 0) {
      flash("Pick a channel and at least one emoji + role pair.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const payload = { channel_id: channelId, title, description, color: color.replace("#", ""), pairs };
      const result = editing
        ? await api.editReactionRoleMessage(guildId, editing.message_id, payload)
        : await api.createReactionRole(guildId, payload);
      flash(editing ? "Updated the reaction-role embed." : `Sent the reaction-role embed with ${pairs.length} role(s).`);
      if (result.failed_reactions?.length) {
        flash(
          `Heads up: couldn't auto-react with ${result.failed_reactions.join(" ")}. The mapping is saved, ` +
            "you may need to react manually with those.",
          "error"
        );
      }
      onCreated(result.reaction_roles);
      if (editing) {
        onCancelEdit();
      } else {
        const blank = emptyState();
        setChannelId(blank.channelId);
        setTitle(blank.title);
        setDescription(blank.description);
        setColor(blank.color);
        setRows(blank.rows);
      }
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
        {editing ? (
          <p className="muted small" style={{ marginTop: 6 }}>
            #{channelNameById[editing.channel_id] || editing.channel_id} (editing can't move channels, use Resend
            for that)
          </p>
        ) : (
          <Combobox options={channels} value={channelId} onChange={setChannelId} placeholder="Pick a channel" />
        )}
      </label>
      <div className="form-row form-row-title-color">
        <label>
          Embed title
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Pick your roles" />
        </label>
        <label>
          Color
          <input type="color" className="color-input" value={color} onChange={(e) => setColor(e.target.value)} />
        </label>
      </div>
      <label>
        Embed description (optional)
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="React below to opt into pings for..."
        />
      </label>

      <div className="rr-rows">
        <div className="rr-row-header">
          <span>Emoji</span>
          <span>Label</span>
          <span>Role</span>
          <span></span>
        </div>
        {rows.map((row, i) => (
          <div className="rr-row" key={i}>
            <EmojiPicker value={row.emoji} onChange={(v) => updateRow(i, "emoji", v)} guildId={guildId} />
            <input
              type="text"
              value={row.label}
              onChange={(e) => updateRow(i, "label", e.target.value)}
              placeholder="e.g. VIP Access"
            />
            <Combobox options={roles} value={row.role_id} onChange={(v) => updateRow(i, "role_id", v)}
                      placeholder="Pick a role" />
            <button
              type="button"
              className="btn btn-ghost btn-small btn-icon"
              onClick={() => removeRow(i)}
              disabled={rows.length === 1}
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      <button type="button" className="btn btn-ghost btn-small" onClick={addRow}>
        <Plus size={14} /> Add another role
      </button>
      <EmbedPreview title={title} description={previewDescription} color={color} />
      <div className="form-spacer" />
      <div className="rr-submit-row">
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? <Spinner size={14} /> : null}
          {submitting ? "Saving…" : editing ? "Save changes" : "Send embed & start listening"}
        </button>
        {editing && (
          <button type="button" className="btn btn-ghost" onClick={onCancelEdit} disabled={submitting}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

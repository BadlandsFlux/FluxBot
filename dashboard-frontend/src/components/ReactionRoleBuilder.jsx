import { useState } from "react";
import { Plus, X } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";
import Combobox from "./Combobox";
import EmojiPicker from "./EmojiPicker";
import EmbedPreview from "./EmbedPreview";

export default function ReactionRoleBuilder({ guildId, roles, channels, onCreated }) {
  const flash = useFlash();
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("Pick your roles");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState("#5865f2");
  const [rows, setRows] = useState([{ emoji: "", label: "", role_id: "" }]);
  const [submitting, setSubmitting] = useState(false);

  function updateRow(index, field, value) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, { emoji: "", label: "", role_id: "" }]);
  }

  function removeRow(index) {
    setRows((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== index) : prev));
  }

  const roleNameById = Object.fromEntries(roles.map((r) => [r.id, r.name]));
  const previewLines = rows
    .filter((r) => r.emoji && r.role_id)
    .map((r) => {
      const roleName = roleNameById[r.role_id] || r.role_id;
      return r.label ? `${r.emoji} **${r.label}** — @${roleName}` : `${r.emoji} — @${roleName}`;
    });
  const previewDescription = [description, previewLines.join("\n")].filter(Boolean).join("\n\n");

  async function handleSubmit(e) {
    e.preventDefault();
    const pairs = rows.filter((r) => r.emoji && r.role_id);
    if (!channelId || pairs.length === 0) {
      flash("Pick a channel and at least one emoji + role pair.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const result = await api.createReactionRole(guildId, {
        channel_id: channelId,
        title,
        description,
        color: color.replace("#", ""),
        pairs,
      });
      flash(`Sent the reaction-role embed with ${pairs.length} role(s).`);
      if (result.failed_reactions?.length) {
        flash(
          `Heads up: couldn't auto-react with ${result.failed_reactions.join(" ")}. The mapping is saved, ` +
            "you may need to react manually with those.",
          "error"
        );
      }
      setChannelId("");
      setTitle("Pick your roles");
      setDescription("");
      setColor("#5865f2");
      setRows([{ emoji: "", label: "", role_id: "" }]);
      onCreated(result.reaction_roles);
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
            <EmojiPicker value={row.emoji} onChange={(v) => updateRow(i, "emoji", v)} />
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
      <button className="btn btn-primary" type="submit" disabled={submitting}>
        {submitting ? <Spinner size={14} /> : null}
        {submitting ? "Sending…" : "Send embed & start listening"}
      </button>
    </form>
  );
}

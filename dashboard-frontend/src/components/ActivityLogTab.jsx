import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Combobox from "./Combobox";
import Switch from "./Switch";
import Spinner from "./Spinner";

const CATEGORIES = [
  { key: "log_message_edits", label: "Message edits", description: "Shows the before and after text, plus a jump link to the message." },
  { key: "log_message_deletes", label: "Message deletes", description: "Shows the deleted content, if the bot saw it get sent." },
  { key: "log_member_joins", label: "Member joins", description: "Includes how old the account is." },
  { key: "log_member_leaves", label: "Member leaves", description: "" },
  { key: "log_channel_changes", label: "Channel changes", description: "Created, deleted, or updated, with who did it where determinable." },
  { key: "log_role_changes", label: "Role changes", description: "Created, deleted, or updated, including the permission set and what changed." },
  { key: "log_voice_activity", label: "Voice activity", description: "Joins, leaves, and switching channels, not mute/deafen toggles." },
  { key: "log_privileged_role_changes", label: "Privileged role changes", description: "A member gaining or losing a role with elevated permissions (kick, ban, manage roles, etc.), separate from general role-object changes above." },
];

export default function ActivityLogTab({ guildId, channels }) {
  const flash = useFlash();
  const [settings, setSettings] = useState(null);
  const [saving, setSaving] = useState(false);
  const [newIgnoredId, setNewIgnoredId] = useState("");

  function load() {
    api
      .getActivityLog(guildId)
      .then(setSettings)
      .catch((e) => flash(e.message, "error"));
  }

  useEffect(load, [guildId]);

  async function handleSave() {
    setSaving(true);
    try {
      const result = await api.setActivityLog(guildId, settings);
      setSettings(result);
      flash("Saved.");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddIgnored(e) {
    e.preventDefault();
    if (!newIgnoredId.trim()) return;
    try {
      const result = await api.addIgnoredLogUser(guildId, newIgnoredId.trim());
      setSettings(result);
      setNewIgnoredId("");
    } catch (err) {
      flash(err.message, "error");
    }
  }

  async function handleRemoveIgnored(userId) {
    try {
      const result = await api.removeIgnoredLogUser(guildId, userId);
      setSettings(result);
    } catch (err) {
      flash(err.message, "error");
    }
  }

  if (!settings) {
    return (
      <div className="card loading-row">
        <Spinner />
        <span className="muted">Loading…</span>
      </div>
    );
  }

  return (
    <>
      <div className="card">
        <h2>Activity Log</h2>
        <p className="muted small">
          Broader server activity, message edits/deletes, member joins/leaves, channel and role changes, voice
          activity, distinct from the Mod Log which only covers actions this bot itself took. Everything below is
          off until you turn it on.
        </p>

        <label>
          Log channel
          <Combobox options={channels} value={settings.log_channel_id || ""}
                    onChange={(v) => setSettings((s) => ({ ...s, log_channel_id: v }))}
                    placeholder="No log channel set, nothing will post anywhere" />
        </label>

        <div className="activity-log-toggles">
          {CATEGORIES.map((cat) => (
            <div className="activity-log-toggle-row" key={cat.key}>
              <div>
                <div className="switch-label">{cat.label}</div>
                {cat.description && <div className="muted small">{cat.description}</div>}
              </div>
              <Switch
                checked={settings[cat.key]}
                onChange={(v) => setSettings((s) => ({ ...s, [cat.key]: v }))}
              />
            </div>
          ))}
        </div>

        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? <Spinner size={14} /> : null}
          {saving ? "Saving…" : "Save settings"}
        </button>
      </div>

      <div className="card">
        <h2>Ignored users</h2>
        <p className="muted small">Nothing about these users gets logged, regardless of which categories are on. Useful for other bots or a very chatty automation.</p>
        {settings.ignored_users.length ? (
          <ul className="chip-list">
            {settings.ignored_users.map((userId) => (
              <li className="chip" key={userId}>
                <code>{userId}</code>
                <button className="chip-remove" onClick={() => handleRemoveIgnored(userId)} title="Remove">
                  <Trash2 size={12} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">None ignored.</p>
        )}
        <form onSubmit={handleAddIgnored} className="inline-form">
          <input
            type="text"
            placeholder="User ID"
            value={newIgnoredId}
            onChange={(e) => setNewIgnoredId(e.target.value)}
          />
          <button className="btn btn-primary btn-small" type="submit">Add</button>
        </form>
      </div>
    </>
  );
}

import { useEffect, useState } from "react";
import { Trash2, AlertTriangle, Radio, Send, Link as LinkIcon } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Combobox from "./Combobox";
import Switch from "./Switch";
import Spinner from "./Spinner";

const DIRECTION_LABELS = {
  discord_to_fluxer: "Discord → Fluxer",
  fluxer_to_discord: "Fluxer → Discord",
  both: "Both ways",
};

const DIRECTION_ARROWS = {
  discord_to_fluxer: "→",
  fluxer_to_discord: "←",
  both: "↔",
};

export default function DiscordRelayTab({ guildId, channels }) {
  const flash = useFlash();
  const [data, setData] = useState(null);
  const [newDiscordId, setNewDiscordId] = useState("");
  const [newFluxerChannel, setNewFluxerChannel] = useState("");
  const [newDirection, setNewDirection] = useState("discord_to_fluxer");
  const [newShowAttribution, setNewShowAttribution] = useState(true);
  const [testingId, setTestingId] = useState(null);

  function load() {
    api
      .getDiscordRelay(guildId)
      .then(setData)
      .catch((e) => flash(e.message, "error"));
  }

  useEffect(load, [guildId]);

  async function handleAdd(e) {
    e.preventDefault();
    if (!newDiscordId.trim() || !newFluxerChannel) {
      flash("Fill in both a Discord channel ID and a Fluxer channel.", "error");
      return;
    }
    try {
      const result = await api.addDiscordRelay(guildId, newDiscordId.trim(), newFluxerChannel, newDirection, newShowAttribution);
      setData((d) => ({ ...d, mappings: result.mappings }));
      setNewDiscordId("");
      setNewFluxerChannel("");
      flash("Added.");
    } catch (err) {
      flash(err.message, "error");
    }
  }

  async function handleRemove(mappingId) {
    try {
      const result = await api.removeDiscordRelay(guildId, mappingId);
      setData((d) => ({ ...d, mappings: result.mappings }));
      flash("Removed.");
    } catch (err) {
      flash(err.message, "error");
    }
  }

  async function handleToggle(mappingId, enabled) {
    try {
      const result = await api.toggleDiscordRelay(guildId, mappingId, enabled);
      setData((d) => ({ ...d, mappings: result.mappings }));
    } catch (err) {
      flash(err.message, "error");
    }
  }

  async function handleTest(mappingId) {
    setTestingId(mappingId);
    try {
      const result = await api.testDiscordRelay(guildId, mappingId);
      const lines = Object.entries(result.results).map(([platform, outcome]) => `${platform}: ${outcome}`);
      flash(lines.join(" \u00b7 "), Object.values(result.results).every((v) => v === "sent") ? "success" : "error");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setTestingId(null);
    }
  }

  if (!data) {
    return (
      <div className="card loading-row">
        <Spinner />
        <span className="muted">Loading…</span>
      </div>
    );
  }

  const channelNameById = Object.fromEntries(channels.map((c) => [c.id, c.name]));

  return (
    <div className="card">
      <h2>Discord Relay</h2>
      <p className="muted small">
        Watches specific channels on a Discord server and forwards new messages, text, embeds, and attachments,
        into a channel here, or the other way too if you pick a two-way mapping. Edits and deletes sync too for
        anything the relay itself sent. Needs its own Discord Bot application, separate from this bot's Fluxer bot.
      </p>

      {data.relay_status && (
        <div className="relay-status-row">
          <Radio size={14} className={data.relay_status.connected ? "relay-status-dot-on" : "relay-status-dot-off"} />
          <span>
            {data.relay_status.connected
              ? `Connected${data.relay_status.discord_username ? ` as ${data.relay_status.discord_username}` : ""}`
              : "Not connected"}
          </span>
        </div>
      )}

      {data.invite_url && (
        <a href={data.invite_url} target="_blank" rel="noreferrer" className="btn btn-ghost btn-small">
          <LinkIcon size={14} /> Invite this bot to a Discord server
        </a>
      )}

      {!data.relay_configured && (
        <div className="banner banner-warning">
          <AlertTriangle size={16} />
          <span>
            The Discord relay isn't set up on this bot yet. Mappings below can still be added, they just won't
            forward anything until the bot owner finishes setup on the Discord Relay Setup page.
          </span>
        </div>
      )}

      {data.mappings.length ? (
        <div className="relay-mapping-list">
          {data.mappings.map((m) => (
            <div className={`relay-mapping-row ${!m.enabled ? "relay-mapping-row-disabled" : ""}`} key={m.id}>
              <div className="relay-mapping-info">
                <div>
                  Discord <code>{m.discord_channel_id}</code> {DIRECTION_ARROWS[m.direction]}{" "}
                  #{channelNameById[m.fluxer_channel_id] || m.fluxer_channel_id}
                </div>
                <div className="muted small">
                  {DIRECTION_LABELS[m.direction]}{m.show_attribution ? "" : ", no attribution"}
                </div>
              </div>
              <div className="relay-mapping-controls">
                <Switch checked={m.enabled} onChange={(v) => handleToggle(m.id, v)} />
                <button className="chip-remove" onClick={() => handleTest(m.id)} disabled={testingId === m.id} title="Send test message">
                  {testingId === m.id ? <Spinner size={12} /> : <Send size={12} />}
                </button>
                <button className="chip-remove" onClick={() => handleRemove(m.id)} title="Remove">
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">No channels being relayed yet.</p>
      )}

      <form onSubmit={handleAdd} className="inline-form relay-add-form">
        <input
          type="text"
          placeholder="Discord channel ID"
          value={newDiscordId}
          onChange={(e) => setNewDiscordId(e.target.value)}
        />
        <Combobox options={channels} value={newFluxerChannel} onChange={setNewFluxerChannel}
                  placeholder="Pick a Fluxer channel" />
        <select value={newDirection} onChange={(e) => setNewDirection(e.target.value)}>
          <option value="discord_to_fluxer">Discord → Fluxer</option>
          <option value="fluxer_to_discord">Fluxer → Discord</option>
          <option value="both">Both ways</option>
        </select>
        <label className="relay-attribution-check">
          <input type="checkbox" checked={newShowAttribution} onChange={(e) => setNewShowAttribution(e.target.checked)} />
          Show who sent it
        </label>
        <button className="btn btn-primary btn-small" type="submit">Add</button>
      </form>
    </div>
  );
}

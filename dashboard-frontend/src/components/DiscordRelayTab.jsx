import { useEffect, useState } from "react";
import { Trash2, AlertTriangle, Radio } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Combobox from "./Combobox";
import Spinner from "./Spinner";

const DIRECTION_LABELS = {
  discord_to_fluxer: "Discord → Fluxer",
  fluxer_to_discord: "Fluxer → Discord",
  both: "Both ways",
};

export default function DiscordRelayTab({ guildId, channels }) {
  const flash = useFlash();
  const [data, setData] = useState(null);
  const [newDiscordId, setNewDiscordId] = useState("");
  const [newFluxerChannel, setNewFluxerChannel] = useState("");
  const [newDirection, setNewDirection] = useState("discord_to_fluxer");

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
      const result = await api.addDiscordRelay(guildId, newDiscordId.trim(), newFluxerChannel, newDirection);
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
        into a channel here, or the other way too if you pick a two-way mapping. Needs its own Discord Bot
        application, separate from this bot's Fluxer bot.
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

      {!data.relay_configured && (
        <div className="banner banner-warning">
          <AlertTriangle size={16} />
          <span>
            The Discord relay isn't set up on this bot yet. Mappings below can still be added, they just won't
            forward anything until the bot owner finishes setup on the Bot Profile page.
          </span>
        </div>
      )}

      {data.mappings.length ? (
        <ul className="chip-list">
          {data.mappings.map((m) => (
            <li className="chip" key={m.id}>
              Discord <code>{m.discord_channel_id}</code> {m.direction === "fluxer_to_discord" ? "←" : m.direction === "both" ? "↔" : "→"}{" "}
              #{channelNameById[m.fluxer_channel_id] || m.fluxer_channel_id}
              <span className="muted small">({DIRECTION_LABELS[m.direction]})</span>
              <button className="chip-remove" onClick={() => handleRemove(m.id)} title="Remove">
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No channels being relayed yet.</p>
      )}

      <form onSubmit={handleAdd} className="inline-form">
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
        <button className="btn btn-primary btn-small" type="submit">Add</button>
      </form>
    </div>
  );
}

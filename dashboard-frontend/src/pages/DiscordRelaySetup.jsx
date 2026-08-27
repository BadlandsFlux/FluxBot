import { useEffect, useState } from "react";
import { Radio, CheckCircle2, XCircle, ExternalLink } from "lucide-react";
import { api } from "../api";
import { useFlash } from "../components/Flash";
import Spinner from "../components/Spinner";
import usePolling from "../hooks/usePolling";

const STEPS = [
  {
    title: "Create the application",
    body: (
      <>
        Go to the{" "}
        <a href="https://discord.com/developers/applications" target="_blank" rel="noreferrer">
          Discord Developer Portal <ExternalLink size={11} />
        </a>
        , click <strong>New Application</strong>, and give it any name, it's just for your own reference.
      </>
    ),
  },
  {
    title: "Enable Message Content Intent",
    body: "On the Bot tab, scroll to Privileged Gateway Intents and turn on Message Content Intent. Without this, the relay only sees metadata, not the actual message text, embeds, or attachments.",
  },
  {
    title: "Get the bot token",
    body: 'Still on the Bot tab, click Reset Token, then Copy. Paste it below, it\'s never shown again in Discord\'s own UI after this.',
  },
  {
    title: "Invite it to your server",
    body: "Under OAuth2 → URL Generator, check the bot scope, then View Channels and Read Message History under Bot Permissions (add Send Messages too if you want two-way relaying). Open the generated URL and add it to your server.",
  },
  {
    title: "Get a channel ID",
    body: "In Discord, turn on User Settings → Advanced → Developer Mode, then right-click any channel and Copy Channel ID. Use that when adding a mapping on a server's Discord Relay tab.",
  },
];

export default function DiscordRelaySetup() {
  const flash = useFlash();
  const [config, setConfig] = useState(null);
  const [tokenInput, setTokenInput] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    api
      .getDiscordRelayConfig()
      .then(setConfig)
      .catch((e) => flash(e.message, "error"));
  }

  useEffect(load, []);
  usePolling(load, 10000);

  async function handleSave(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.setDiscordRelayToken(tokenInput.trim());
      setTokenInput("");
      flash("Saved. Connecting…");
      setTimeout(load, 2000);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  if (!config) {
    return (
      <div className="card loading-row">
        <Spinner />
        <span className="muted">Loading…</span>
      </div>
    );
  }

  const status = config.status;

  return (
    <>
      <div className="card">
        <h2>
          <Radio size={18} /> Discord Relay Setup
        </h2>
        <p className="muted small">
          Owner-only. One Discord Bot application powers relaying for every server this bot manages, individual
          channel mappings are configured per-server on that server's Discord Relay tab.
        </p>

        <div className="relay-status-row">
          {status?.connected ? (
            <CheckCircle2 size={16} className="relay-status-dot-on" />
          ) : (
            <XCircle size={16} className="relay-status-dot-off" />
          )}
          <span>
            {status?.connected
              ? `Connected as ${status.discord_username || "unknown"}`
              : config.token_configured
              ? "Configured, but not currently connected"
              : "Not set up yet"}
          </span>
        </div>
        {status?.last_error && !status.connected && (
          <p className="muted small">Last error: {status.last_error}</p>
        )}
        {config.token_source === "env" && (
          <p className="muted small">Currently using the token from this bot's DISCORD_BOT_TOKEN environment variable.</p>
        )}

        <form onSubmit={handleSave} className="inline-form">
          <input
            type="password"
            placeholder={config.token_configured ? "Enter a new token to replace it" : "Paste your bot token"}
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary btn-small" type="submit" disabled={saving || !tokenInput.trim()}>
            {saving ? <Spinner size={14} /> : "Save"}
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Setup steps</h2>
        <div className="step-list">
          {STEPS.map((step, i) => (
            <div className="step-item" key={i}>
              <div className="step-number">{i + 1}</div>
              <div>
                <div className="step-title">{step.title}</div>
                <div className="muted small">{step.body}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

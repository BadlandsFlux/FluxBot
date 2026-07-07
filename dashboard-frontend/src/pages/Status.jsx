import { useEffect, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import { api } from "../api";
import Spinner from "../components/Spinner";
import usePolling from "../hooks/usePolling";

function formatUptime(seconds) {
  if (seconds == null) return null;
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours || days) parts.push(`${hours}h`);
  parts.push(`${minutes}m`);
  return parts.join(" ");
}

export default function Status() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  function load() {
    api
      .status()
      .then(setData)
      .catch((e) => setError(e.message));
  }

  useEffect(load, []);
  usePolling(load, 15000);

  if (error) {
    return (
      <div className="card empty-state">
        <p className="error">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="loading-row">
        <Spinner />
        <span className="muted">Checking status…</span>
      </div>
    );
  }

  const uptime = formatUptime(data.bot_uptime_seconds);

  return (
    <div className="card status-page">
      <div className={`status-banner ${data.bot_online ? "status-ok" : "status-down"}`}>
        {data.bot_online ? <CheckCircle2 size={28} /> : <XCircle size={28} />}
        <span>{data.bot_online ? "All systems operational" : "Bot is offline"}</span>
      </div>

      <div className="status-grid">
        <div className="status-item">
          <div className="status-value">{uptime || "—"}</div>
          <div className="muted small">Uptime</div>
        </div>
        <div className="status-item">
          <div className="status-value">{data.gateway_latency_ms != null ? `${data.gateway_latency_ms}ms` : "—"}</div>
          <div className="muted small">Gateway latency</div>
        </div>
        <div className="status-item">
          <div className="status-value">{data.guild_count ?? "—"}</div>
          <div className="muted small">Servers</div>
        </div>
        <div className="status-item">
          <div className="status-value">{data.dashboard_db_ok ? `${data.dashboard_db_latency_ms}ms` : "down"}</div>
          <div className="muted small">Database</div>
        </div>
      </div>

      <p className="muted small status-footer">Refreshes automatically every 15 seconds.</p>
    </div>
  );
}

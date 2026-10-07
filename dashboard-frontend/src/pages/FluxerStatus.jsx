import { useEffect, useState } from "react";
import { CheckCircle2, AlertTriangle, HelpCircle } from "lucide-react";
import { api } from "../api";
import Spinner from "../components/Spinner";
import usePolling from "../hooks/usePolling";

const REFRESH_MS = 20000;

function formatUptime(seconds) {
  if (seconds == null) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours || days) parts.push(`${hours}h`);
  parts.push(`${minutes}m`);
  return parts.join(" ");
}

function formatBytes(bytes) {
  if (bytes == null) return "—";
  // Fluxer serializes these as JSON strings, not numbers, so they don't
  // lose precision on instances with memory counts past JS's safe
  // integer range. Number() up front rather than relying on the loop's
  // own arithmetic to coerce it, since a value under 1024 skips the
  // loop entirely and would otherwise still be a string when .toFixed()
  // runs below (strings don't have that method).
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = Number(bytes);
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`;
}

const STATUS_BANNER = {
  healthy: { icon: CheckCircle2, className: "status-ok", label: "All nodes healthy" },
  degraded: { icon: AlertTriangle, className: "status-down", label: "Degraded, one or more nodes aren't responding favorably" },
  unknown: { icon: HelpCircle, className: "status-unknown", label: "Couldn't reach the Fluxer admin API just now" },
};

export default function FluxerStatus() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notConfigured, setNotConfigured] = useState(false);

  function load() {
    api
      .fluxerStats()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (e.status === 400) {
          setNotConfigured(true);
        } else {
          setError(e.message);
        }
      });
  }

  useEffect(load, []);
  usePolling(load, REFRESH_MS, !notConfigured && !error);

  if (notConfigured) {
    return (
      <div className="card empty-state">
        <p className="muted">
          <code>FLUXER_ADMIN_API_KEY</code> isn't set, so there's nothing to show here. Generate an admin API key on
          your Fluxer instance with the <code>admin:authenticate</code> and <code>gateway:memory_stats</code>{" "}
          permissions, then add it to your <code>.env</code> (see <code>.env.example</code>).
        </p>
      </div>
    );
  }

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
        <span className="muted">Loading Fluxer server stats…</span>
      </div>
    );
  }

  const banner = STATUS_BANNER[data.status] || STATUS_BANNER.unknown;
  const BannerIcon = banner.icon;
  const nodes = data.nodes || [];

  return (
    <div className="card status-page fluxer-status-page">
      <h1>Fluxer server status</h1>
      <p className="muted small">
        Live platform infrastructure stats from your Fluxer instance's admin API. Refreshes every {REFRESH_MS / 1000}s.
      </p>

      <div className={`status-banner ${banner.className}`}>
        <BannerIcon size={28} />
        <span>{banner.label}</span>
      </div>

      <div className="status-grid">
        <div className="status-item">
          <div className="status-value">{data.sessions ?? "—"}</div>
          <div className="muted small">Connected sessions</div>
        </div>
        <div className="status-item">
          <div className="status-value">{data.guilds ?? "—"}</div>
          <div className="muted small">Active guild processes</div>
        </div>
        <div className="status-item">
          <div className="status-value">{data.presences ?? "—"}</div>
          <div className="muted small">Tracked presences</div>
        </div>
        <div className="status-item">
          <div className="status-value">{data.calls ?? "—"}</div>
          <div className="muted small">Live voice calls</div>
        </div>
        <div className="status-item">
          <div className="status-value">{formatUptime(data.uptime_seconds)}</div>
          <div className="muted small">Uptime (lowest among nodes)</div>
        </div>
        <div className="status-item">
          <div className="status-value">{data.node_count ?? "—"}</div>
          <div className="muted small">Nodes</div>
        </div>
        <div className="status-item">
          <div className="status-value">
            {data.process_count != null && data.process_limit != null
              ? `${data.process_count} / ${data.process_limit}`
              : "—"}
          </div>
          <div className="muted small">Erlang processes</div>
        </div>
        <div className="status-item">
          <div className="status-value">{formatBytes(data.memory?.total)}</div>
          <div className="muted small">Memory (total)</div>
        </div>
      </div>

      {data.memory && (
        <>
          <h2 className="section-divider">Memory breakdown</h2>
          <div className="status-grid">
            <div className="status-item">
              <div className="status-value">{formatBytes(data.memory.processes)}</div>
              <div className="muted small">Processes</div>
            </div>
            <div className="status-item">
              <div className="status-value">{formatBytes(data.memory.system)}</div>
              <div className="muted small">System</div>
            </div>
          </div>
        </>
      )}

      {nodes.length > 0 && (
        <>
          <h2 className="section-divider">Per-node breakdown</h2>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Node</th>
                  <th>Status</th>
                  <th>Sessions</th>
                  <th>Guilds</th>
                  <th>Uptime</th>
                  <th>Memory</th>
                </tr>
              </thead>
              <tbody>
                {nodes.map((n, i) => (
                  <tr key={n.node_id || n.name || i}>
                    <td><code>{n.node_id || n.name || `node ${i + 1}`}</code></td>
                    <td>
                      <span className={`tag ${n.status === "healthy" ? "tag-unban" : "tag-ban"}`}>
                        {n.status || "unknown"}
                      </span>
                    </td>
                    <td>{n.sessions ?? "—"}</td>
                    <td>{n.guilds ?? "—"}</td>
                    <td>{formatUptime(n.uptime_seconds)}</td>
                    <td>{formatBytes(n.memory?.total ?? n.memory)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="muted small status-footer">
        This is Fluxer's own "live state": consecutive reads can differ even without any administrative action.
      </p>
    </div>
  );
}

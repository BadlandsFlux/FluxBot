import { useEffect, useState } from "react";
import { Ban, Clock, LogOut, ShieldAlert, Search } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";

const DURATIONS = [
  { label: "10 minutes", seconds: 600 },
  { label: "1 hour", seconds: 3600 },
  { label: "1 day", seconds: 86400 },
  { label: "1 week", seconds: 604800 },
];

const ACTION_META = {
  warn: { label: "Warn", icon: ShieldAlert, needsDuration: false },
  timeout: { label: "Timeout", icon: Clock, needsDuration: true },
  kick: { label: "Kick", icon: LogOut, needsDuration: false },
  ban: { label: "Ban", icon: Ban, needsDuration: false },
};

export default function MembersTab({ guildId, roles }) {
  const flash = useFlash();
  const [query, setQuery] = useState("");
  const [members, setMembers] = useState(null);
  const [error, setError] = useState(null);
  const [pendingAction, setPendingAction] = useState(null); // {userId, type}
  const [reason, setReason] = useState("");
  const [durationSeconds, setDurationSeconds] = useState(3600);
  const [submitting, setSubmitting] = useState(false);

  const roleNameById = Object.fromEntries(roles.map((r) => [r.id, r.name]));

  function load(q) {
    api
      .members(guildId, q)
      .then((d) => setMembers(d.members))
      .catch((e) => setError(e.message));
  }

  useEffect(() => {
    load("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guildId]);

  useEffect(() => {
    const t = setTimeout(() => load(query), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  function openAction(userId, type) {
    setPendingAction({ userId, type });
    setReason("");
    setDurationSeconds(3600);
  }

  async function confirmAction() {
    if (!pendingAction) return;
    const { userId, type } = pendingAction;
    setSubmitting(true);
    try {
      if (type === "warn") {
        const result = await api.warnMember(guildId, userId, reason);
        flash(`Warned — ${result.result.active_count} active warning(s).${
          result.result.escalated ? ` Auto-${result.result.escalated}ed.` : ""
        }`);
      } else if (type === "timeout") {
        await api.timeoutMember(guildId, userId, reason, durationSeconds);
        flash("Timed out.");
      } else if (type === "kick") {
        await api.kickMember(guildId, userId, reason);
        flash("Kicked.");
        setMembers((prev) => prev.filter((m) => m.id !== userId));
      } else if (type === "ban") {
        await api.banMember(guildId, userId, reason);
        flash("Banned.");
        setMembers((prev) => prev.filter((m) => m.id !== userId));
      }
      setPendingAction(null);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  if (error) {
    return (
      <div className="card empty-state">
        <p className="error">{error}</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Members</h2>
      <p className="muted small">
        Search covers up to the first 500 members fetched from Fluxer. For huge servers, search by exact user ID
        if someone doesn't show up.
      </p>
      <div className="search-box">
        <Search size={16} className="search-icon" />
        <input
          type="text"
          placeholder="Search by username or ID…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {members === null ? (
        <div className="loading-row">
          <Spinner />
          <span className="muted">Loading members…</span>
        </div>
      ) : members.length === 0 ? (
        <p className="muted">No members match.</p>
      ) : (
        <div className="member-list">
          {members.map((m) => (
            <div className="member-row" key={m.id}>
              <div className="member-info">
                <div className="member-avatar">{m.username ? m.username[0].toUpperCase() : "?"}</div>
                <div>
                  <div className="member-name">{m.username}</div>
                  <div className="muted small">
                    <code>{m.id}</code>
                    {m.roles.length > 0 && (
                      <span> · {m.roles.map((r) => roleNameById[r] || r).join(", ")}</span>
                    )}
                  </div>
                </div>
              </div>

              {pendingAction?.userId === m.id ? (
                <div className="member-action-panel">
                  <input
                    type="text"
                    placeholder="Reason (optional)"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    autoFocus
                  />
                  {ACTION_META[pendingAction.type].needsDuration && (
                    <select value={durationSeconds} onChange={(e) => setDurationSeconds(Number(e.target.value))}>
                      {DURATIONS.map((d) => (
                        <option key={d.seconds} value={d.seconds}>
                          {d.label}
                        </option>
                      ))}
                    </select>
                  )}
                  <button className="btn btn-primary btn-small" onClick={confirmAction} disabled={submitting}>
                    {submitting ? <Spinner size={12} /> : `Confirm ${ACTION_META[pendingAction.type].label}`}
                  </button>
                  <button className="btn btn-ghost btn-small" onClick={() => setPendingAction(null)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="member-actions">
                  {Object.entries(ACTION_META).map(([type, meta]) => {
                    const Icon = meta.icon;
                    return (
                      <button
                        key={type}
                        className="btn btn-ghost btn-small btn-icon"
                        title={meta.label}
                        onClick={() => openAction(m.id, type)}
                      >
                        <Icon size={14} />
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

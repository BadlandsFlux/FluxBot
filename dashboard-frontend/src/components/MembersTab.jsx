import { useEffect, useState } from "react";
import { Ban, Clock, LogOut, ShieldAlert, Search, Users, StickyNote, Plus, Trash2 } from "lucide-react";
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

const ACTION_CALL = {
  warn: (guildId, userId, reason) => api.warnMember(guildId, userId, reason),
  timeout: (guildId, userId, reason, duration) => api.timeoutMember(guildId, userId, reason, duration),
  kick: (guildId, userId, reason) => api.kickMember(guildId, userId, reason),
  ban: (guildId, userId, reason) => api.banMember(guildId, userId, reason),
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
  const [notesOpenFor, setNotesOpenFor] = useState(null);
  const [notes, setNotes] = useState([]);
  const [notesLoading, setNotesLoading] = useState(false);
  const [newNote, setNewNote] = useState("");

  const [selected, setSelected] = useState(new Set());
  const [bulkAction, setBulkAction] = useState(null); // {type}
  const [bulkReason, setBulkReason] = useState("");
  const [bulkDuration, setBulkDuration] = useState(3600);
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkProgress, setBulkProgress] = useState(null); // {done, total}

  const roleNameById = Object.fromEntries(roles.map((r) => [r.id, r.name]));

  function load(q) {
    api
      .members(guildId, q)
      .then((d) => {
        setMembers(d.members);
        setSelected(new Set());
      })
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

  async function toggleNotes(userId) {
    if (notesOpenFor === userId) {
      setNotesOpenFor(null);
      return;
    }
    setNotesOpenFor(userId);
    setNewNote("");
    setNotesLoading(true);
    try {
      const data = await api.listMemberNotes(guildId, userId);
      setNotes(data.notes);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setNotesLoading(false);
    }
  }

  async function addNote(userId) {
    if (!newNote.trim()) return;
    try {
      const data = await api.addMemberNote(guildId, userId, newNote.trim());
      setNotes(data.notes);
      setNewNote("");
    } catch (err) {
      flash(err.message, "error");
    }
  }

  async function removeNoteRow(userId, noteId) {
    try {
      const data = await api.removeMemberNote(guildId, userId, noteId);
      setNotes(data.notes);
    } catch (err) {
      flash(err.message, "error");
    }
  }

  async function confirmAction() {
    if (!pendingAction) return;
    const { userId, type } = pendingAction;
    setSubmitting(true);
    try {
      if (type === "warn") {
        const result = await api.warnMember(guildId, userId, reason);
        flash(`Warned, ${result.result.active_count} active warning(s).${
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

  function toggleSelect(userId) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  function toggleSelectAll() {
    if (!members) return;
    setSelected((prev) => (prev.size === members.length ? new Set() : new Set(members.map((m) => m.id))));
  }

  function openBulkAction(type) {
    setBulkAction({ type });
    setBulkReason("");
    setBulkDuration(3600);
  }

  async function confirmBulkAction() {
    if (!bulkAction) return;
    const ids = [...selected];
    setBulkRunning(true);
    setBulkProgress({ done: 0, total: ids.length });
    let succeeded = 0;
    let failed = 0;
    for (const userId of ids) {
      try {
        await ACTION_CALL[bulkAction.type](guildId, userId, bulkReason, bulkDuration);
        succeeded += 1;
      } catch {
        failed += 1;
      }
      setBulkProgress((p) => ({ done: p.done + 1, total: p.total }));
    }
    setBulkRunning(false);
    setBulkProgress(null);
    setBulkAction(null);
    flash(
      `${ACTION_META[bulkAction.type].label}ed ${succeeded} member(s).${failed ? ` ${failed} failed.` : ""}`,
      failed ? "error" : undefined
    );
    if (bulkAction.type === "kick" || bulkAction.type === "ban") {
      setMembers((prev) => prev.filter((m) => !selected.has(m.id)));
    }
    setSelected(new Set());
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

      {selected.size > 0 && (
        <div className="bulk-action-bar">
          <span>
            <Users size={14} /> {selected.size} selected
          </span>
          {bulkAction ? (
            <div className="member-action-panel">
              <input
                type="text"
                placeholder="Reason (optional)"
                value={bulkReason}
                onChange={(e) => setBulkReason(e.target.value)}
                autoFocus
              />
              {ACTION_META[bulkAction.type].needsDuration && (
                <select value={bulkDuration} onChange={(e) => setBulkDuration(Number(e.target.value))}>
                  {DURATIONS.map((d) => (
                    <option key={d.seconds} value={d.seconds}>{d.label}</option>
                  ))}
                </select>
              )}
              <button className="btn btn-primary btn-small" onClick={confirmBulkAction} disabled={bulkRunning}>
                {bulkRunning
                  ? `${bulkProgress?.done ?? 0}/${bulkProgress?.total ?? selected.size}…`
                  : `Confirm ${ACTION_META[bulkAction.type].label} (${selected.size})`}
              </button>
              <button className="btn btn-ghost btn-small" onClick={() => setBulkAction(null)} disabled={bulkRunning}>
                Cancel
              </button>
            </div>
          ) : (
            <div className="bulk-action-buttons">
              {Object.entries(ACTION_META).map(([type, meta]) => {
                const Icon = meta.icon;
                return (
                  <button key={type} className="btn btn-ghost btn-small" onClick={() => openBulkAction(type)}>
                    <Icon size={13} /> {meta.label}
                  </button>
                );
              })}
              <button className="btn btn-ghost btn-small" onClick={() => setSelected(new Set())}>
                Clear selection
              </button>
            </div>
          )}
        </div>
      )}

      {members === null ? (
        <div className="loading-row">
          <Spinner />
          <span className="muted">Loading members…</span>
        </div>
      ) : members.length === 0 ? (
        <p className="muted">No members match.</p>
      ) : (
        <>
          <label className="select-all-row">
            <input type="checkbox" checked={selected.size === members.length} onChange={toggleSelectAll} />
            Select all {members.length} shown
          </label>
          <div className="member-list">
            {members.map((m) => (
              <div className="member-row" key={m.id}>
                <div className="member-info">
                  <input
                    type="checkbox"
                    checked={selected.has(m.id)}
                    onChange={() => toggleSelect(m.id)}
                    className="member-checkbox"
                  />
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
                  <button
                    className="btn btn-ghost btn-small btn-icon"
                    title="Staff notes"
                    onClick={() => toggleNotes(m.id)}
                  >
                    <StickyNote size={14} />
                  </button>
                </div>
              )}

              {notesOpenFor === m.id && (
                <div className="member-notes-panel">
                  {notesLoading ? (
                    <div className="loading-row"><Spinner size={14} /><span className="muted small">Loading notes…</span></div>
                  ) : (
                    <>
                      {notes.length ? (
                        <ul className="member-notes-list">
                          {notes.map((n) => (
                            <li key={n.id}>
                              <span>{n.note}</span>
                              <span className="muted small">by <code>{n.created_by}</code></span>
                              <button className="chip-remove" onClick={() => removeNoteRow(m.id, n.id)} title="Remove">
                                <Trash2 size={12} />
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted small">No notes on this member yet.</p>
                      )}
                      <form
                        className="inline-form"
                        onSubmit={(e) => {
                          e.preventDefault();
                          addNote(m.id);
                        }}
                      >
                        <input
                          type="text"
                          placeholder="Add a private note (staff only)…"
                          value={newNote}
                          onChange={(e) => setNewNote(e.target.value)}
                        />
                        <button className="btn btn-primary btn-small" type="submit">
                          <Plus size={14} /> Add
                        </button>
                      </form>
                    </>
                  )}
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
        </>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { Plus, Minus, Trash2 } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";
import Combobox from "./Combobox";

export default function LevelsTab({ guildId, roles }) {
  const flash = useFlash();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [newLevel, setNewLevel] = useState("");
  const [newRole, setNewRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [xpAmounts, setXpAmounts] = useState({}); // userId -> input value
  const [xpBusyFor, setXpBusyFor] = useState(null);
  const roleNameById = Object.fromEntries(roles.map((r) => [r.id, r.name]));

  function load() {
    api
      .levels(guildId)
      .then(setData)
      .catch((e) => setError(e.message));
  }

  useEffect(load, [guildId]);

  async function handleAdjust(userId, sign) {
    const raw = Number(xpAmounts[userId]);
    if (!raw || raw <= 0) {
      flash("Enter a positive amount first.", "error");
      return;
    }
    setXpBusyFor(userId);
    try {
      const result = await api.adjustUserXp(guildId, userId, raw * sign);
      setData((d) => ({ ...d, leaderboard: result.leaderboard }));
      setXpAmounts((a) => ({ ...a, [userId]: "" }));
      flash(`${sign > 0 ? "Added" : "Removed"} ${raw} XP.`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setXpBusyFor(null);
    }
  }

  async function handleResetUser(userId, username) {
    if (!window.confirm(`Reset ${username}'s XP and level back to zero?`)) return;
    setXpBusyFor(userId);
    try {
      const result = await api.resetUserXp(guildId, userId);
      setData((d) => ({ ...d, leaderboard: result.leaderboard }));
      flash(`Reset ${username}'s XP.`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setXpBusyFor(null);
    }
  }

  async function handleAddLevelRole(e) {
    e.preventDefault();
    const level = Number(newLevel);
    if (!level || level < 1 || !newRole) {
      flash("Give a level (1+) and pick a role.", "error");
      return;
    }
    setBusy(true);
    try {
      const result = await api.addLevelRole(guildId, level, newRole);
      setData((d) => ({ ...d, level_roles: result.level_roles }));
      setNewLevel("");
      setNewRole("");
      flash(`Level ${level} now grants ${roleNameById[newRole] || newRole}.`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(level) {
    try {
      const result = await api.removeLevelRole(guildId, level);
      setData((d) => ({ ...d, level_roles: result.level_roles }));
      flash(`Removed the level ${level} role reward.`);
    } catch (err) {
      flash(err.message, "error");
    }
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
        <span className="muted">Loading levels…</span>
      </div>
    );
  }

  return (
    <>
      <div className="card">
        <h2>Leaderboard</h2>
        {data.leaderboard.length ? (
          <table className="table">
            <thead>
              <tr><th>#</th><th>User</th><th>Level</th><th>XP</th><th>Manage XP</th></tr>
            </thead>
            <tbody>
              {data.leaderboard.map((row, i) => (
                <tr key={row.user_id}>
                  <td>{i + 1}</td>
                  <td>{row.username}</td>
                  <td>{row.level}</td>
                  <td>{row.xp}</td>
                  <td>
                    <div className="xp-manage-row">
                      <input
                        type="number"
                        min={1}
                        placeholder="Amount"
                        value={xpAmounts[row.user_id] || ""}
                        onChange={(e) => setXpAmounts((a) => ({ ...a, [row.user_id]: e.target.value }))}
                      />
                      <button
                        className="btn btn-ghost btn-small btn-icon"
                        title="Add XP"
                        onClick={() => handleAdjust(row.user_id, 1)}
                        disabled={xpBusyFor === row.user_id}
                      >
                        <Plus size={13} />
                      </button>
                      <button
                        className="btn btn-ghost btn-small btn-icon"
                        title="Remove XP"
                        onClick={() => handleAdjust(row.user_id, -1)}
                        disabled={xpBusyFor === row.user_id}
                      >
                        <Minus size={13} />
                      </button>
                      <button
                        className="btn btn-ghost btn-small"
                        onClick={() => handleResetUser(row.user_id, row.username)}
                        disabled={xpBusyFor === row.user_id}
                      >
                        {xpBusyFor === row.user_id ? <Spinner size={12} /> : "Reset"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No one has earned XP yet.</p>
        )}
      </div>

      <div className="card">
        <h2>Level-role rewards</h2>
        <p className="muted small">Automatically grant a role when a member reaches a level.</p>
        {data.level_roles.length ? (
          <ul className="chip-list">
            {data.level_roles.map((lr) => (
              <li className="chip" key={lr.id}>
                Level {lr.level} → {roleNameById[lr.role_id] || <code>{lr.role_id}</code>}
                <button className="chip-remove" onClick={() => handleRemove(lr.level)} title="Remove">
                  <Trash2 size={12} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">None set yet.</p>
        )}
        <form onSubmit={handleAddLevelRole} className="inline-form">
          <input
            type="number"
            min={1}
            value={newLevel}
            onChange={(e) => setNewLevel(e.target.value)}
            placeholder="Level"
            style={{ maxWidth: 90 }}
          />
          <Combobox options={roles} value={newRole} onChange={setNewRole} placeholder="Pick a role" />
          <button className="btn btn-primary btn-small" type="submit" disabled={busy}>
            <Plus size={14} /> Add
          </button>
        </form>
      </div>
    </>
  );
}

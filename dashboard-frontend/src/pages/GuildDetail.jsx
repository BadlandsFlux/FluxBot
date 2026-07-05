import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  LayoutGrid, Settings, ShieldAlert, ScrollText, UserPlus, Smile, ArrowLeft, Trash2, Plus, Users,
  Tag as TagIcon, TrendingUp, Megaphone, Search,
} from "lucide-react";
import { api } from "../api";
import { useFlash } from "../components/Flash";
import Spinner from "../components/Spinner";
import ReactionRoleBuilder from "../components/ReactionRoleBuilder";
import Combobox from "../components/Combobox";
import Switch from "../components/Switch";
import MembersTab from "../components/MembersTab";
import TagsTab from "../components/TagsTab";
import LevelsTab from "../components/LevelsTab";
import DangerZone from "../components/DangerZone";
import AnnouncementBuilder from "../components/AnnouncementBuilder";
import BarChart from "../components/BarChart";
import useRolesChannels from "../hooks/useRolesChannels";
import usePolling from "../hooks/usePolling";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutGrid },
  { id: "settings", label: "Settings", icon: Settings },
  { id: "members", label: "Members", icon: Users },
  { id: "warnings", label: "Warnings", icon: ShieldAlert },
  { id: "modlog", label: "Mod Log", icon: ScrollText },
  { id: "autoroles", label: "Autoroles", icon: UserPlus },
  { id: "reactionroles", label: "Reaction Roles", icon: Smile },
  { id: "levels", label: "Levels", icon: TrendingUp },
  { id: "tags", label: "Tags", icon: TagIcon },
  { id: "announce", label: "Announce", icon: Megaphone },
];

const ACTION_TAG_CLASS = {
  ban: "tag-ban", kick: "tag-kick", timeout: "tag-timeout", warn: "tag-warn",
  unban: "tag-unban", untimeout: "tag-untimeout", clearwarnings: "tag-clearwarnings", purge: "tag-purge",
  danger_clear_warnings: "tag-ban", danger_reset_xp: "tag-ban", danger_wipe_reaction_roles: "tag-ban",
};

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function GuildDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [lastSynced, setLastSynced] = useState(null);
  const tab = params.get("tab") || "overview";
  const { roles, channels } = useRolesChannels(id);

  function setTab(next) {
    setParams((p) => {
      p.set("tab", next);
      return p;
    });
  }

  const load = useCallback(
    (silent = false) =>
      api
        .guildDetail(id)
        .then((d) => {
          setData(d);
          setLastSynced(new Date());
          if (!silent) setError(null);
        })
        .catch((e) => !silent && setError(e.message)),
    [id]
  );

  useEffect(() => {
    setData(null);
    setError(null);
    load();
  }, [id, load]);

  // Live-ish updates: quietly refetch every 8s so kicks/bans/warnings from
  // chat commands (or another admin) show up without a manual refresh.
  // Paused on the Settings tab so it can't clobber an in-progress edit.
  usePolling(() => load(true), 8000, tab !== "settings" && !!data);

  if (error) {
    return (
      <div className="card empty-state">
        <p className="error">{error}</p>
        <Link className="btn btn-ghost btn-small" to="/">
          ← Back to your servers
        </Link>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="loading-row">
        <Spinner />
        <span className="muted">Loading server…</span>
      </div>
    );
  }

  const {
    guild, actions, warnings, autoroles, reaction_roles: reactionRoles, tags,
    active_warning_count: activeWarningCount,
  } = data;

  return (
    <>
      <Link className="back-link" to="/">
        <ArrowLeft size={13} /> Your servers
      </Link>
      <div className="page-head page-head-row">
        <div>
          <h1>{guild.name}</h1>
        </div>
        {lastSynced && (
          <div className="live-indicator" title={`Last updated ${lastSynced.toLocaleTimeString()}`}>
            <span className="live-dot" /> Live
          </div>
        )}
      </div>

      <nav className="tabs-nav">
        {TABS.map((t) => {
          const Icon = t.icon;
          const count =
            t.id === "warnings" ? activeWarningCount
            : t.id === "autoroles" ? autoroles.length
            : t.id === "reactionroles" ? reactionRoles.length
            : t.id === "tags" ? tags.length
            : null;
          return (
            <button key={t.id} className={`tab-btn ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
              <Icon size={14} />
              {t.label}
              {count !== null && <span className="tab-count">{count}</span>}
            </button>
          );
        })}
      </nav>

      {tab === "overview" && (
        <OverviewTab guildId={id} guild={guild} actions={actions} autoroles={autoroles} reactionRoles={reactionRoles}
                     tags={tags} activeWarningCount={activeWarningCount} />
      )}
      {tab === "settings" && (
        <SettingsTab guildId={id} guild={guild} roles={roles} channels={channels}
                     onSaved={(g) => setData((d) => ({ ...d, guild: g }))}
                     onWarningsCleared={() => setData((d) => ({
                       ...d,
                       warnings: d.warnings.map((w) => ({ ...w, active: false })),
                       active_warning_count: 0,
                     }))}
                     onReactionRolesWiped={() => setData((d) => ({ ...d, reaction_roles: [] }))} />
      )}
      {tab === "members" && <MembersTab guildId={id} roles={roles} />}
      {tab === "warnings" && (
        <WarningsTab guildId={id} warnings={warnings}
                     onCleared={(w, count) => setData((d) => ({ ...d, warnings: w, active_warning_count: count }))} />
      )}
      {tab === "modlog" && <ModLogTab actions={actions} />}
      {tab === "autoroles" && (
        <AutorolesTab guildId={id} autoroles={autoroles} roles={roles}
                      onChange={(a) => setData((d) => ({ ...d, autoroles: a }))} />
      )}
      {tab === "reactionroles" && (
        <ReactionRolesTab guildId={id} reactionRoles={reactionRoles} roles={roles} channels={channels}
                          onChange={(r) => setData((d) => ({ ...d, reaction_roles: r }))} />
      )}
      {tab === "tags" && (
        <TagsTab guildId={id} tags={tags} prefix={guild.command_prefix || "!"}
                 onChange={(t) => setData((d) => ({ ...d, tags: t }))} />
      )}
      {tab === "levels" && <LevelsTab guildId={id} roles={roles} />}
      {tab === "announce" && (
        <div className="card">
          <h2>Send an announcement</h2>
          <p className="muted small">Compose a rich embed and post it to any channel.</p>
          <AnnouncementBuilder guildId={id} channels={channels} />
        </div>
      )}
    </>
  );
}

function StatCard({ value, label }) {
  return (
    <div className="card stat-card">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function OverviewTab({ guildId, guild, actions, autoroles, reactionRoles, tags, activeWarningCount }) {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.stats(guildId, 14).then(setStats).catch(() => {});
  }, [guildId]);

  return (
    <>
      <div className="stat-grid">
        <StatCard value={guild.command_prefix || "!"} label="Prefix" />
        <StatCard value={activeWarningCount} label="Active warnings" />
        <StatCard value={actions.length} label="Logged mod actions" />
        <StatCard value={autoroles.length} label="Autoroles" />
        <StatCard value={reactionRoles.length} label="Reaction role mappings" />
        <StatCard value={tags.length} label="Tags" />
      </div>

      {stats && (
        <div className="card">
          <h2>Message activity — last 14 days</h2>
          <div className="stat-grid" style={{ marginBottom: 16 }}>
            <StatCard value={stats.total_messages_30d} label="Messages (30d)" />
          </div>
          {stats.daily.some((d) => d.count > 0) ? (
            <BarChart
              data={stats.daily.map((d) => ({ label: d.date, value: d.count }))}
              formatLabel={(d) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            />
          ) : (
            <p className="muted small">No message activity recorded yet.</p>
          )}
          {stats.top_members.length > 0 && (
            <>
              <h2 className="section-divider">Most active in chat</h2>
              <div className="top-members-list">
                {stats.top_members.map((m, i) => (
                  <div className="top-member-row" key={m.user_id}>
                    <span className="muted">#{i + 1}</span>
                    <span className="top-member-name">{m.username}</span>
                    <span className="muted small">{m.count} messages</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {stats && (
        <div className="card">
          <h2>Voice activity — last 14 days</h2>
          <p className="muted small">
            Only counts time with 2+ people connected and not self-deafened — solo/AFK time doesn't count.
          </p>
          {stats.daily.some((d) => d.voice_minutes > 0) ? (
            <BarChart
              data={stats.daily.map((d) => ({ label: d.date, value: d.voice_minutes }))}
              formatLabel={(d) => new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
            />
          ) : (
            <p className="muted small">No qualifying voice activity recorded yet.</p>
          )}
          {stats.top_voice_members.length > 0 && (
            <>
              <h2 className="section-divider">Most active in voice</h2>
              <div className="top-members-list">
                {stats.top_voice_members.map((m, i) => (
                  <div className="top-member-row" key={m.user_id}>
                    <span className="muted">#{i + 1}</span>
                    <span className="top-member-name">{m.username}</span>
                    <span className="muted small">{m.minutes} min</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <div className="card">
        <h2>Recent activity</h2>
        {actions.length ? (
          <table className="table">
            <thead>
              <tr><th>Action</th><th>User</th><th>Moderator</th><th>When</th></tr>
            </thead>
            <tbody>
              {actions.slice(0, 8).map((a) => (
                <tr key={a.id}>
                  <td><span className={`tag ${ACTION_TAG_CLASS[a.action] || ""}`}>{a.action}</span></td>
                  <td><code>{a.user_id || "—"}</code></td>
                  <td><code>{a.moderator_id || "system"}</code></td>
                  <td>{fmt(a.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No mod actions logged yet.</p>
        )}
      </div>
    </>
  );
}

function SettingsTab({ guildId, guild, roles, channels, onSaved, onWarningsCleared, onReactionRolesWiped }) {
  const flash = useFlash();
  const [form, setForm] = useState(guild);
  const [welcomeOn, setWelcomeOn] = useState(!!guild.welcome_channel_id);
  const [goodbyeOn, setGoodbyeOn] = useState(!!guild.goodbye_channel_id);
  const [levelingOn, setLevelingOn] = useState(!!guild.leveling_enabled);
  const [saving, setSaving] = useState(false);

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function toggleWelcome(next) {
    setWelcomeOn(next);
    if (!next) set("welcome_channel_id", "");
  }

  function toggleGoodbye(next) {
    setGoodbyeOn(next);
    if (!next) set("goodbye_channel_id", "");
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const result = await api.updateSettings(guildId, {
        log_channel_id: form.log_channel_id || "",
        mute_role_id: form.mute_role_id || "",
        command_prefix: form.command_prefix || "!",
        welcome_channel_id: welcomeOn ? form.welcome_channel_id || "" : "",
        welcome_message: form.welcome_message || "Welcome {user} to {server}! 👋",
        goodbye_channel_id: goodbyeOn ? form.goodbye_channel_id || "" : "",
        goodbye_message: form.goodbye_message || "{username} left {server}. 👋",
        leveling_enabled: levelingOn,
        level_up_channel_id: form.level_up_channel_id || "",
        level_up_message: form.level_up_message || "GG {user}, you reached level {level}! 🎉",
        warn_timeout_at: Number(form.warn_timeout_at),
        warn_kick_at: Number(form.warn_kick_at),
        warn_timeout_minutes: Number(form.warn_timeout_minutes),
      });
      onSaved(result.guild);
      setWelcomeOn(!!result.guild.welcome_channel_id);
      setGoodbyeOn(!!result.guild.goodbye_channel_id);
      setLevelingOn(!!result.guild.leveling_enabled);
      flash("Settings saved.");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className="card">
      <h2>Moderation settings</h2>
      <form onSubmit={handleSubmit} className="settings-form">
        <label>
          Mod-log channel
          <Combobox options={channels} value={form.log_channel_id || ""}
                    onChange={(v) => set("log_channel_id", v)} placeholder="No mod-log channel set" />
        </label>
        <label>
          Command prefix
          <input type="text" value={form.command_prefix || "!"} maxLength={5}
                 onChange={(e) => set("command_prefix", e.target.value)} placeholder="!" />
        </label>
        <label>
          Mute role (fallback if timeout API is unavailable)
          <Combobox options={roles} value={form.mute_role_id || ""}
                    onChange={(v) => set("mute_role_id", v)} placeholder="No mute role set" />
        </label>
        <div className="form-row form-row-3">
          <label>
            Warn count → auto-timeout
            <input type="number" min={1} value={form.warn_timeout_at} onChange={(e) => set("warn_timeout_at", e.target.value)} />
          </label>
          <label>
            Warn count → auto-kick
            <input type="number" min={1} value={form.warn_kick_at} onChange={(e) => set("warn_kick_at", e.target.value)} />
          </label>
          <label>
            Auto-timeout length (minutes)
            <input type="number" min={1} value={form.warn_timeout_minutes} onChange={(e) => set("warn_timeout_minutes", e.target.value)} />
          </label>
        </div>

        <h2 className="section-divider">Welcome messages</h2>
        <Switch checked={welcomeOn} onChange={toggleWelcome} label="Send a welcome message when someone joins" />
        {welcomeOn && (
          <div className="switch-panel">
            <label>
              Welcome channel
              <Combobox options={channels} value={form.welcome_channel_id || ""}
                        onChange={(v) => set("welcome_channel_id", v)} placeholder="Pick a channel" />
            </label>
            <label>
              Message — <code>{"{user}"}</code> mentions them, <code>{"{username}"}</code>, <code>{"{server}"}</code>,{" "}
              <code>{"{membercount}"}</code> also work
              <input type="text" value={form.welcome_message || ""} onChange={(e) => set("welcome_message", e.target.value)}
                     placeholder="Welcome {user} to {server}! 👋" />
            </label>
            {!form.welcome_channel_id && (
              <p className="muted small">Pick a channel above to finish turning this on.</p>
            )}
          </div>
        )}

        <h2 className="section-divider">Goodbye messages</h2>
        <Switch checked={goodbyeOn} onChange={toggleGoodbye} label="Send a message when someone leaves" />
        {goodbyeOn && (
          <div className="switch-panel">
            <label>
              Goodbye channel
              <Combobox options={channels} value={form.goodbye_channel_id || ""}
                        onChange={(v) => set("goodbye_channel_id", v)} placeholder="Pick a channel" />
            </label>
            <label>
              Message — <code>{"{username}"}</code>, <code>{"{server}"}</code>, <code>{"{membercount}"}</code> work
              (no <code>{"{user}"}</code> mention since they've already left)
              <input type="text" value={form.goodbye_message || ""} onChange={(e) => set("goodbye_message", e.target.value)}
                     placeholder="{username} left {server}. 👋" />
            </label>
            {!form.goodbye_channel_id && (
              <p className="muted small">Pick a channel above to finish turning this on.</p>
            )}
          </div>
        )}

        <h2 className="section-divider">Leveling</h2>
        <Switch checked={levelingOn} onChange={setLevelingOn} label="Members earn XP for chatting" />
        {levelingOn && (
          <div className="switch-panel">
            <label>
              Level-up announcement channel
              <Combobox options={channels} value={form.level_up_channel_id || ""}
                        onChange={(v) => set("level_up_channel_id", v)}
                        placeholder="Announce in the channel they leveled up in" />
            </label>
            <label>
              Message, <code>{"{user}"}</code>, <code>{"{username}"}</code>, <code>{"{level}"}</code> work
              <input type="text" value={form.level_up_message || ""} onChange={(e) => set("level_up_message", e.target.value)}
                     placeholder="GG {user}, you reached level {level}! 🎉" />
            </label>
          </div>
        )}

        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? <Spinner size={14} /> : null}
          {saving ? "Saving…" : "Save settings"}
        </button>
      </form>
      </div>

      <DangerZone guildId={guildId} onWarningsCleared={onWarningsCleared} onReactionRolesWiped={onReactionRolesWiped} />
    </>
  );
}

function WarningsTab({ guildId, warnings, onCleared }) {
  const flash = useFlash();
  const [clearingId, setClearingId] = useState(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  async function handleClear(userId) {
    setClearingId(userId);
    try {
      const result = await api.clearWarning(guildId, userId);
      onCleared(result.warnings, result.active_warning_count);
      flash(`Cleared ${result.cleared} warning(s) for ${userId}.`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setClearingId(null);
    }
  }

  const filtered = warnings.filter((w) => {
    if (statusFilter === "active" && !w.active) return false;
    if (statusFilter === "cleared" && w.active) return false;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      const haystack = `${w.user_id} ${w.moderator_id} ${w.reason || ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  return (
    <div className="card">
      <h2>Warnings</h2>
      <div className="filter-bar">
        <div className="search-box">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            placeholder="Search by user ID, moderator ID, or reason…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="all">All statuses</option>
          <option value="active">Active only</option>
          <option value="cleared">Cleared only</option>
        </select>
      </div>
      {warnings.length === 0 ? (
        <p className="muted">No warnings recorded yet.</p>
      ) : filtered.length === 0 ? (
        <p className="muted">No warnings match your filters.</p>
      ) : (
        <table className="table">
          <thead>
            <tr><th>User</th><th>Moderator</th><th>Reason</th><th>When</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {filtered.map((w) => (
              <tr key={w.id}>
                <td><code>{w.user_id}</code></td>
                <td><code>{w.moderator_id}</code></td>
                <td>{w.reason}</td>
                <td>{fmt(w.created_at)}</td>
                <td>
                  {w.active ? <span className="tag tag-warn">active</span> : <span className="tag tag-unban">cleared</span>}
                </td>
                <td>
                  {w.active && (
                    <button className="btn btn-ghost btn-small" onClick={() => handleClear(w.user_id)}
                            disabled={clearingId === w.user_id}>
                      {clearingId === w.user_id ? <Spinner size={12} /> : "Clear"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ModLogTab({ actions }) {
  const [query, setQuery] = useState("");
  const [actionFilter, setActionFilter] = useState("all");

  const actionTypes = [...new Set(actions.map((a) => a.action))].sort();

  const filtered = actions.filter((a) => {
    if (actionFilter !== "all" && a.action !== actionFilter) return false;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      const haystack = `${a.user_id || ""} ${a.moderator_id || ""} ${a.reason || ""}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });

  return (
    <div className="card">
      <h2>Mod action history</h2>
      <div className="filter-bar">
        <div className="search-box">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            placeholder="Search by user ID, moderator ID, or reason…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
          <option value="all">All actions</option>
          {actionTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>
      {actions.length === 0 ? (
        <p className="muted">No mod actions logged yet.</p>
      ) : filtered.length === 0 ? (
        <p className="muted">No actions match your filters.</p>
      ) : (
        <table className="table">
          <thead>
            <tr><th>Action</th><th>User</th><th>Moderator</th><th>Reason</th><th>When</th></tr>
          </thead>
          <tbody>
            {filtered.map((a) => (
              <tr key={a.id}>
                <td><span className={`tag ${ACTION_TAG_CLASS[a.action] || ""}`}>{a.action}</span></td>
                <td><code>{a.user_id || "none"}</code></td>
                <td><code>{a.moderator_id || "system"}</code></td>
                <td>{a.reason}</td>
                <td>{fmt(a.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function AutorolesTab({ guildId, autoroles, roles, onChange }) {
  const flash = useFlash();
  const [newRole, setNewRole] = useState("");
  const [busy, setBusy] = useState(false);
  const roleNameById = Object.fromEntries(roles.map((r) => [r.id, r.name]));
  const availableRoles = roles.filter((r) => !autoroles.includes(r.id));

  async function handleAdd(e) {
    e.preventDefault();
    if (!newRole) return;
    setBusy(true);
    try {
      const result = await api.addAutorole(guildId, newRole);
      onChange(result.autoroles);
      const addedName = roleNameById[newRole] || newRole;
      setNewRole("");
      flash(`Added autorole ${addedName}.`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(roleId) {
    try {
      const result = await api.removeAutorole(guildId, roleId);
      onChange(result.autoroles);
      flash(`Removed autorole ${roleNameById[roleId] || roleId}.`);
    } catch (err) {
      flash(err.message, "error");
    }
  }

  return (
    <div className="card">
      <h2>Autoroles</h2>
      <p className="muted small">Roles automatically given to every member who joins.</p>
      {autoroles.length ? (
        <ul className="chip-list">
          {autoroles.map((r) => (
            <li className="chip" key={r}>
              {roleNameById[r] || <code>{r}</code>}
              <button className="chip-remove" onClick={() => handleRemove(r)} title="Remove">
                <Trash2 size={12} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">None set yet.</p>
      )}
      <form onSubmit={handleAdd} className="inline-form">
        <Combobox options={availableRoles} value={newRole} onChange={setNewRole} placeholder="Pick a role to add" />
        <button className="btn btn-primary btn-small" type="submit" disabled={busy || !newRole}>
          <Plus size={14} /> Add autorole
        </button>
      </form>
    </div>
  );
}

function ReactionRolesTab({ guildId, reactionRoles, roles, channels, onChange }) {
  const flash = useFlash();
  const [deletingId, setDeletingId] = useState(null);
  const roleNameById = Object.fromEntries(roles.map((r) => [r.id, r.name]));
  const channelNameById = Object.fromEntries(channels.map((c) => [c.id, c.name]));

  const messages = [];
  const byMessage = new Map();
  for (const rr of reactionRoles) {
    if (!byMessage.has(rr.message_id)) {
      const group = { message_id: rr.message_id, channel_id: rr.channel_id, entries: [] };
      byMessage.set(rr.message_id, group);
      messages.push(group);
    }
    byMessage.get(rr.message_id).entries.push(rr);
  }

  async function handleDeleteMessage(messageId) {
    setDeletingId(messageId);
    try {
      const result = await api.removeReactionRoleMessage(guildId, messageId);
      onChange(result.reaction_roles);
      flash("Deleted that reaction-role message and all its mappings.");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      <div className="card">
        <h2>Send a reaction-role embed</h2>
        <p className="muted small">
          Posts an embed in the channel you choose. Members react with one of the emojis below to get
          the matching role (and lose it if they remove their reaction).
        </p>
        <ReactionRoleBuilder guildId={guildId} roles={roles} channels={channels} onCreated={onChange} />
      </div>
      <div className="card">
        <h2>Existing reaction-role messages</h2>
        {messages.length ? (
          <div className="rr-message-list">
            {messages.map((group) => (
              <div className="rr-message-card" key={group.message_id}>
                <div className="rr-message-head">
                  <div>
                    <div className="rr-message-channel">
                      #{channelNameById[group.channel_id] || group.channel_id}
                    </div>
                    <div className="muted small">
                      Message <code>{group.message_id}</code>
                    </div>
                  </div>
                  <button
                    className="btn btn-ghost btn-small"
                    onClick={() => handleDeleteMessage(group.message_id)}
                    disabled={deletingId === group.message_id}
                  >
                    {deletingId === group.message_id ? <Spinner size={12} /> : <Trash2 size={13} />}
                    Delete
                  </button>
                </div>
                <div className="rr-message-entries">
                  {group.entries.map((rr) => (
                    <div className="rr-message-entry" key={rr.id}>
                      <span className="rr-entry-emoji">{rr.emoji}</span>
                      {rr.label && <span className="rr-entry-label">{rr.label}</span>}
                      <span className="muted small">→ {roleNameById[rr.role_id] || rr.role_id}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">None set yet, build one above.</p>
        )}
      </div>
    </>
  );
}

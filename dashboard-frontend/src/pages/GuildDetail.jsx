import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  LayoutGrid, Settings, ShieldAlert, ScrollText, UserPlus, Smile, ArrowLeft, Trash2, Plus, Users,
  Tag as TagIcon, TrendingUp, LayoutTemplate, Search, FileClock, ArrowLeftRight, Flag, Pencil, RefreshCw,
  ToggleLeft, ChevronUp, ChevronDown,
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
import ActivityLogTab from "../components/ActivityLogTab";
import DiscordRelayTab from "../components/DiscordRelayTab";
import CommandsTab from "../components/CommandsTab";
import ReportsTab from "../components/ReportsTab";
import OnboardingChecklist from "../components/OnboardingChecklist";
import DangerZone from "../components/DangerZone";
import EmbedBuilder from "../components/EmbedBuilder";
import BarChart from "../components/BarChart";
import HeatmapGrid from "../components/HeatmapGrid";
import GuildSidebar from "../components/GuildSidebar";
import useRolesChannels from "../hooks/useRolesChannels";
import usePolling from "../hooks/usePolling";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutGrid, category: null },
  { id: "members", label: "Members", icon: Users, category: "Moderation" },
  { id: "warnings", label: "Warnings", icon: ShieldAlert, category: "Moderation" },
  { id: "modlog", label: "Mod Log", icon: ScrollText, category: "Moderation" },
  { id: "reports", label: "Reports", icon: Flag, category: "Moderation" },
  { id: "settings", label: "Settings", icon: Settings, category: "Configuration" },
  { id: "autoroles", label: "Autoroles", icon: UserPlus, category: "Configuration" },
  { id: "reactionroles", label: "Reaction Roles", icon: Smile, category: "Configuration" },
  { id: "activitylog", label: "Activity Log", icon: FileClock, category: "Configuration" },
  { id: "discordrelay", label: "Discord Relay", icon: ArrowLeftRight, category: "Configuration" },
  { id: "commands", label: "Commands", icon: ToggleLeft, category: "Configuration" },
  { id: "levels", label: "Levels", icon: TrendingUp, category: "Engagement" },
  { id: "tags", label: "Tags", icon: TagIcon, category: "Engagement" },
  { id: "embed", label: "Embed", icon: LayoutTemplate, category: "Engagement" },
];

const ACTION_TAG_CLASS = {
  ban: "tag-ban", kick: "tag-kick", timeout: "tag-timeout", warn: "tag-warn",
  unban: "tag-unban", untimeout: "tag-untimeout", clearwarnings: "tag-clearwarnings", purge: "tag-purge",
  danger_clear_warnings: "tag-ban", danger_reset_xp: "tag-ban", danger_wipe_reaction_roles: "tag-ban",
  settings_update: "tag-purge",
};

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// The background poll only ever re-fetches the default first page of
// actions/reports, so a wholesale replace would silently drop anything
// revealed by "Load more" every 8 seconds. Keeps the freshly-polled page
// (it's authoritative for anything within it, e.g. a status change) and
// appends whatever was previously loaded further back that isn't in it.
function mergePolledPage(freshPage, existingList) {
  if (!existingList || existingList.length <= freshPage.length) return freshPage;
  const freshIds = new Set(freshPage.map((x) => x.id));
  return [...freshPage, ...existingList.filter((x) => !freshIds.has(x.id))];
}

export default function GuildDetail() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [lastSynced, setLastSynced] = useState(null);
  const [actionsHasMore, setActionsHasMore] = useState(false);
  const [reportsHasMore, setReportsHasMore] = useState(false);
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
          setData((prev) => ({
            ...d,
            actions: mergePolledPage(d.actions, prev?.actions),
            reports: mergePolledPage(d.reports, prev?.reports),
          }));
          // Only the initial/guild-switch load gets to reset this from the
          // page-size heuristic; an in-progress "Load more" already knows
          // the real answer and a silent poll shouldn't second-guess it.
          if (!silent) {
            setActionsHasMore(d.actions.length >= 50);
            setReportsHasMore(d.reports.length >= 100);
          }
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

  // ModLogTab's search box seeds itself from this ?q= param once, via a
  // lazy useState initializer, the first time it mounts (a deep link from
  // Members' "View mod log history"). Clearing it right after means a
  // LATER mount (switching tabs away and back, which unmounts/remounts
  // ModLogTab) starts from a blank search instead of reseeding the same
  // stale value and discarding whatever the user typed in between.
  useEffect(() => {
    if (tab === "modlog" && params.get("q")) {
      setParams((p) => {
        p.delete("q");
        return p;
      }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  async function loadMoreActions() {
    const last = data?.actions?.[data.actions.length - 1];
    if (!last) return;
    const result = await api.loadMoreActions(id, last.id);
    setData((d) => ({ ...d, actions: [...d.actions, ...result.actions] }));
    setActionsHasMore(result.has_more);
  }

  async function loadMoreReports() {
    const last = data?.reports?.[data.reports.length - 1];
    if (!last) return;
    const result = await api.loadMoreReports(id, last.id);
    setData((d) => ({ ...d, reports: [...d.reports, ...result.reports] }));
    setReportsHasMore(result.has_more);
  }

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
    guild, actions, warnings, autoroles, reaction_roles: reactionRoles, tags, reports,
    active_warning_count: activeWarningCount, open_report_count: openReportCount,
    member_count: memberCount, fluxer_status: fluxerStatus,
  } = data;

  const counts = {
    warnings: activeWarningCount,
    autoroles: autoroles.length,
    reactionroles: reactionRoles.length,
    tags: tags.length,
    reports: openReportCount,
  };

  return (
    <div className="guild-layout">
      <GuildSidebar tabs={TABS} activeTab={tab} onTabChange={setTab} counts={counts} />
      <div className="guild-main">
        <Link className="back-link" to="/">
          <ArrowLeft size={13} /> Your servers
        </Link>
        <div className="page-head page-head-row">
          <div>
            <h1>{guild.name}</h1>
          </div>
          <div className="page-head-indicators">
            {fluxerStatus && (
              <div className={`fluxer-status-pill fluxer-status-${fluxerStatus}`} title="Fluxer server status">
                <span className="fluxer-status-dot" />
                Fluxer: {fluxerStatus === "healthy" ? "Operational" : fluxerStatus === "degraded" ? "Degraded" : "Unknown"}
              </div>
            )}
            {lastSynced && (
              <div className="live-indicator" title={`Last updated ${lastSynced.toLocaleTimeString()}`}>
                <span className="live-dot" /> Live
              </div>
            )}
          </div>
        </div>

        <div className="tab-content" key={tab}>
          {tab === "overview" && (
            <OverviewTab guildId={id} guild={guild} actions={actions} autoroles={autoroles} reactionRoles={reactionRoles}
                         tags={tags} roles={roles} channels={channels} activeWarningCount={activeWarningCount}
                         openReportCount={openReportCount} memberCount={memberCount} setTab={setTab} />
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
          {tab === "modlog" && (
            <ModLogTab actions={actions} initialQuery={params.get("q") || ""}
                       hasMore={actionsHasMore} onLoadMore={loadMoreActions} />
          )}
          {tab === "reports" && (
            <ReportsTab guildId={id} guild={guild} channels={channels} reports={reports}
                        hasMore={reportsHasMore} onLoadMore={loadMoreReports}
                        onChange={(result) => setData((d) => {
                          // Merged the same way the background poll already
                          // is (see mergePolledPage above it): a status
                          // update's response is just the first page of
                          // reports, a wholesale replace would silently
                          // drop anything revealed by "Load more" before it.
                          const mergedReports = mergePolledPage(result.reports, d.reports);
                          const openReportCount = result.open_report_count
                            ?? mergedReports.filter((x) => x.status === "open").length;
                          return { ...d, reports: mergedReports, open_report_count: openReportCount };
                        })}
                        onGuildChange={(g) => setData((d) => ({ ...d, guild: g }))} />
          )}
          {tab === "autoroles" && (
            <AutorolesTab guildId={id} autoroles={autoroles} roles={roles}
                          onChange={(a) => setData((d) => ({ ...d, autoroles: a }))} />
          )}
          {tab === "reactionroles" && (
            <ReactionRolesTab guildId={id} reactionRoles={reactionRoles} roles={roles} channels={channels}
                              onChange={(r) => setData((d) => ({ ...d, reaction_roles: r }))} />
          )}
          {tab === "activitylog" && <ActivityLogTab guildId={id} channels={channels} />}
          {tab === "discordrelay" && <DiscordRelayTab guildId={id} channels={channels} />}
          {tab === "commands" && <CommandsTab guildId={id} />}
          {tab === "tags" && (
            <TagsTab guildId={id} tags={tags} prefix={guild.command_prefix || "!"}
                     onChange={(t) => setData((d) => ({ ...d, tags: t }))} />
          )}
          {tab === "levels" && (
            <LevelsTab guildId={id} guild={guild} roles={roles} channels={channels}
                       onSaved={(g) => setData((d) => ({ ...d, guild: g }))} />
          )}
          {tab === "embed" && (
            <div className="card">
              <h2>Send an embed</h2>
              <p className="muted small">Compose a rich embed, with headers, fields, and formatting, and post it to any channel.</p>
              <EmbedBuilder guildId={id} channels={channels} />
            </div>
          )}
        </div>
      </div>
    </div>
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

function AttentionRow({ activeWarningCount, openReportCount, setTab }) {
  if (activeWarningCount === 0 && openReportCount === 0) {
    return <p className="muted small attention-clear">Nothing needs attention right now.</p>;
  }
  return (
    <div className="attention-row">
      {activeWarningCount > 0 && (
        <button type="button" className="attention-pill" onClick={() => setTab("warnings")}>
          <ShieldAlert size={14} /> {activeWarningCount} active warning{activeWarningCount !== 1 ? "s" : ""}
        </button>
      )}
      {openReportCount > 0 && (
        <button type="button" className="attention-pill" onClick={() => setTab("reports")}>
          <Flag size={14} /> {openReportCount} open report{openReportCount !== 1 ? "s" : ""}
        </button>
      )}
    </div>
  );
}

// Persistent, non-dismissible counterpart to OnboardingChecklist: that
// one nudges toward finishing setup and then disappears forever once
// everything's checked off (or dismissed), after which there was no
// remaining at-a-glance view of what's actually configured. This stays
// put so "is leveling on?" never requires a trip into Settings to answer.
function FeatureStatusRow({ guild, setTab }) {
  const items = [
    { key: "modlog", label: "Mod-log", on: !!guild.log_channel_id, tab: "settings" },
    { key: "welcome", label: "Welcome", on: !!guild.welcome_channel_id, tab: "settings" },
    { key: "goodbye", label: "Goodbye", on: !!guild.goodbye_channel_id, tab: "settings" },
    { key: "leveling", label: "Leveling", on: !!guild.leveling_enabled, tab: "levels" },
    { key: "reports", label: "Reports", on: !!guild.report_channel_id, tab: "settings" },
  ];
  return (
    <div className="feature-status-row">
      {items.map((item) => (
        <button type="button" key={item.key} onClick={() => setTab(item.tab)} title={`Go to ${item.tab === "levels" ? "Levels" : "Settings"}`}
                className={`feature-status-pill ${item.on ? "feature-status-on" : "feature-status-off"}`}>
          <span className="feature-status-dot" /> {item.label}
        </button>
      ))}
    </div>
  );
}

function OverviewTab({ guildId, guild, actions, autoroles, reactionRoles, tags, roles, channels,
                       activeWarningCount, openReportCount, memberCount, setTab }) {
  const [stats, setStats] = useState(null);
  const [showHeatmap, setShowHeatmap] = useState(false);

  useEffect(() => {
    api.stats(guildId, 14).then(setStats).catch(() => {});
  }, [guildId]);

  return (
    <>
      <OnboardingChecklist guild={guild} autoroles={autoroles} reactionRoles={reactionRoles} tags={tags} setTab={setTab} />

      <AttentionRow activeWarningCount={activeWarningCount} openReportCount={openReportCount} setTab={setTab} />
      <FeatureStatusRow guild={guild} setTab={setTab} />

      <div className="stat-grid">
        <StatCard value={memberCount ?? "—"} label="Members" />
        <StatCard value={channels.length} label="Channels" />
        <StatCard value={roles.length} label="Roles" />
        <StatCard value={guild.command_prefix || "!"} label="Prefix" />
        <StatCard value={autoroles.length} label="Autoroles" />
        <StatCard value={reactionRoles.length} label="Reaction role mappings" />
        <StatCard value={tags.length} label="Tags" />
        <StatCard value={actions.length} label="Logged mod actions" />
      </div>

      {stats && (
        <div className="overview-two-col">
          <div className="card">
            <h2>Message activity, last 14 days</h2>
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

          <div className="card">
            <h2>Voice activity, last 14 days</h2>
            <p className="muted small">
              Only counts time with 2+ people connected and not self-deafened, solo/AFK time doesn't count.
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
        </div>
      )}

      <div className="overview-two-col">
        <div className="card">
          <h2>Most-used commands</h2>
          {!stats ? (
            <div className="loading-row"><Spinner size={16} /></div>
          ) : stats.top_commands.length > 0 ? (
            <div className="top-members-list">
              {stats.top_commands.map((c, i) => (
                <div className="top-member-row" key={c.name}>
                  <span className="muted">#{i + 1}</span>
                  <span className="top-member-name">!{c.name}</span>
                  <span className="muted small">{c.count} use{c.count !== 1 ? "s" : ""}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted small">No commands used yet.</p>
          )}
        </div>

        <div className="card">
          <div className="overview-card-head">
            <h2>Recent activity</h2>
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setTab("modlog")}>
              View full mod log →
            </button>
          </div>
          {actions.length ? (
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr><th>Action</th><th>User</th><th>Moderator</th><th>When</th></tr>
                </thead>
                <tbody>
                  {actions.slice(0, 5).map((a) => (
                    <tr key={a.id}>
                      <td><span className={`tag ${ACTION_TAG_CLASS[a.action] || ""}`}>{a.action}</span></td>
                      <td>
                        {a.user_id ? (
                          <>
                            <div>{a.username}</div>
                            <div className="muted small"><code>{a.user_id}</code></div>
                          </>
                        ) : (
                          <span className="muted">none</span>
                        )}
                      </td>
                      <td>
                        {a.moderator_id ? (
                          <>
                            <div>{a.moderator_username}</div>
                            <div className="muted small"><code>{a.moderator_id}</code></div>
                          </>
                        ) : (
                          <span className="muted">system</span>
                        )}
                      </td>
                      <td>{fmt(a.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No mod actions logged yet.</p>
          )}
        </div>
      </div>

      {stats && stats.heatmap.length > 0 && (
        <div className="card">
          <div className="overview-card-head">
            <div>
              <h2>When the server's actually busy</h2>
              <p className="muted small">
                Message activity by hour and day, all-time, in your local time. Useful for picking event times.
              </p>
            </div>
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setShowHeatmap((s) => !s)}>
              {showHeatmap ? <ChevronUp size={14} /> : <ChevronDown size={14} />} {showHeatmap ? "Hide" : "Show"}
            </button>
          </div>
          {showHeatmap && <HeatmapGrid data={stats.heatmap} />}
        </div>
      )}
    </>
  );
}

function SettingsTab({ guildId, guild, roles, channels, onSaved, onWarningsCleared, onReactionRolesWiped }) {
  const flash = useFlash();
  const [form, setForm] = useState(guild);
  const [welcomeOn, setWelcomeOn] = useState(!!guild.welcome_channel_id);
  const [goodbyeOn, setGoodbyeOn] = useState(!!guild.goodbye_channel_id);
  const [reportsOn, setReportsOn] = useState(!!guild.report_channel_id);
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

  function toggleReports(next) {
    setReportsOn(next);
    if (!next) {
      set("report_channel_id", "");
      set("report_tracker_channel_id", "");
    }
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
        // Leveling settings live on the Levels tab now; pass through
        // whatever's already on this guild unedited so saving Settings
        // can never clobber them back to the payload's own defaults.
        leveling_enabled: form.leveling_enabled,
        level_up_channel_id: form.level_up_channel_id || "",
        level_up_message: form.level_up_message || "GG {user}, you reached level {level}! 🎉",
        voice_xp_cap_enabled: form.voice_xp_cap_enabled ?? true,
        voice_xp_cap_amount: form.voice_xp_cap_amount ?? 750,
        warn_timeout_at: Number(form.warn_timeout_at),
        warn_kick_at: Number(form.warn_kick_at),
        warn_timeout_minutes: Number(form.warn_timeout_minutes),
        report_channel_id: reportsOn ? form.report_channel_id || "" : "",
        report_tracker_channel_id: reportsOn ? form.report_tracker_channel_id || "" : "",
      });
      onSaved(result.guild);
      setWelcomeOn(!!result.guild.welcome_channel_id);
      setGoodbyeOn(!!result.guild.goodbye_channel_id);
      setReportsOn(!!result.guild.report_channel_id);
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
              Message, <code>{"{user}"}</code> mentions them, <code>{"{username}"}</code>, <code>{"{server}"}</code>,{" "}
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
              Message, <code>{"{username}"}</code>, <code>{"{server}"}</code>, <code>{"{membercount}"}</code> work
              (no <code>{"{user}"}</code> mention since they've already left)
              <input type="text" value={form.goodbye_message || ""} onChange={(e) => set("goodbye_message", e.target.value)}
                     placeholder="{username} left {server}. 👋" />
            </label>
            {!form.goodbye_channel_id && (
              <p className="muted small">Pick a channel above to finish turning this on.</p>
            )}
          </div>
        )}

        <h2 className="section-divider">Bug/issue reports</h2>
        <Switch checked={reportsOn} onChange={toggleReports}
                label="Capture reports from a dedicated channel, no command needed" />
        {reportsOn && (
          <div className="switch-panel">
            <label>
              Report channel: any message posted here becomes a report
              <Combobox options={channels} value={form.report_channel_id || ""}
                        onChange={(v) => set("report_channel_id", v)} placeholder="Pick a channel" />
            </label>
            <label>
              Tracker channel: status-tagged log of every report, so people can check before filing another
              <Combobox options={channels} value={form.report_tracker_channel_id || ""}
                        onChange={(v) => set("report_tracker_channel_id", v)} placeholder="Optional, but recommended" />
            </label>
            {!form.report_channel_id && (
              <p className="muted small">Pick a channel above to finish turning this on.</p>
            )}
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
      const haystack = `${w.username} ${w.user_id} ${w.moderator_username} ${w.moderator_id} ${w.reason || ""}`.toLowerCase();
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
            placeholder="Search by username, ID, or reason…"
            aria-label="Search warnings by username, ID, or reason"
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
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr><th>User</th><th>Moderator</th><th>Reason</th><th>When</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {filtered.map((w) => (
                <tr key={w.id}>
                  <td>
                    <div>{w.username}</div>
                    <div className="muted small"><code>{w.user_id}</code></div>
                  </td>
                  <td>
                    <div>{w.moderator_username}</div>
                    <div className="muted small"><code>{w.moderator_id}</code></div>
                  </td>
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
        </div>
      )}
    </div>
  );
}

function ModLogTab({ actions, initialQuery = "", hasMore, onLoadMore }) {
  // Lazy initializer, runs once: a deep link from Members (?q=<userId>)
  // seeds the search box, but typing afterward isn't fought by the URL.
  const [query, setQuery] = useState(() => initialQuery);
  const [actionFilter, setActionFilter] = useState("all");
  const [loadingMore, setLoadingMore] = useState(false);

  const actionTypes = [...new Set(actions.map((a) => a.action))].sort();

  const filtered = actions.filter((a) => {
    if (actionFilter !== "all" && a.action !== actionFilter) return false;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      const haystack = `${a.username || ""} ${a.user_id || ""} ${a.moderator_username || ""} ${a.moderator_id || ""} ${a.reason || ""}`.toLowerCase();
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
            placeholder="Search by username, ID, or reason…"
            aria-label="Search mod log by username, ID, or reason"
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
        <>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr><th>Action</th><th>User</th><th>Moderator</th><th>Reason</th><th>When</th></tr>
              </thead>
              <tbody>
                {filtered.map((a) => (
                  <tr key={a.id}>
                    <td><span className={`tag ${ACTION_TAG_CLASS[a.action] || ""}`}>{a.action}</span></td>
                    <td>
                      {a.user_id ? (
                        <>
                          <div>{a.username}</div>
                          <div className="muted small"><code>{a.user_id}</code></div>
                        </>
                      ) : (
                        <span className="muted">none</span>
                      )}
                    </td>
                    <td>
                      {a.moderator_id ? (
                        <>
                          <div>{a.moderator_username}</div>
                          <div className="muted small"><code>{a.moderator_id}</code></div>
                        </>
                      ) : (
                        <span className="muted">system</span>
                      )}
                    </td>
                    <td>{a.reason}</td>
                    <td>{fmt(a.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hasMore && (
            <button
              className="btn btn-ghost btn-small"
              disabled={loadingMore}
              onClick={async () => {
                setLoadingMore(true);
                try {
                  await onLoadMore();
                } finally {
                  setLoadingMore(false);
                }
              }}
            >
              {loadingMore ? <Spinner size={12} /> : null} Load more
            </button>
          )}
        </>
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
  const [resendingId, setResendingId] = useState(null);
  const [editingMessageId, setEditingMessageId] = useState(null);
  const builderRef = useRef(null);
  const roleNameById = Object.fromEntries(roles.map((r) => [r.id, r.name]));
  const channelNameById = Object.fromEntries(channels.map((c) => [c.id, c.name]));

  const messages = [];
  const byMessage = new Map();
  for (const rr of reactionRoles) {
    if (!byMessage.has(rr.message_id)) {
      const group = {
        message_id: rr.message_id, channel_id: rr.channel_id,
        title: rr.title, description: rr.description, color: rr.color, entries: [],
      };
      byMessage.set(rr.message_id, group);
      messages.push(group);
    }
    byMessage.get(rr.message_id).entries.push(rr);
  }
  const editing = editingMessageId ? messages.find((m) => m.message_id === editingMessageId) || null : null;

  useEffect(() => {
    // Lost the message we were editing (e.g. a resend from elsewhere, or
    // it got deleted out from under us): drop back to create mode instead
    // of leaving a stale edit open on data that no longer exists.
    if (editingMessageId && !editing) setEditingMessageId(null);
  }, [editingMessageId, editing]);

  function startEdit(messageId) {
    setEditingMessageId(messageId);
    builderRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function handleDeleteMessage(messageId) {
    setDeletingId(messageId);
    try {
      const result = await api.removeReactionRoleMessage(guildId, messageId);
      onChange(result.reaction_roles);
      if (editingMessageId === messageId) setEditingMessageId(null);
      flash("Deleted that reaction-role message and all its mappings.");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleResend(messageId) {
    setResendingId(messageId);
    try {
      const result = await api.resendReactionRoleMessage(guildId, messageId);
      onChange(result.reaction_roles);
      if (editingMessageId === messageId) setEditingMessageId(null);
      flash("Resent as a new message, the old one (if it still existed) was cleaned up.");
      if (result.failed_reactions?.length) {
        flash(
          `Heads up: couldn't auto-react with ${result.failed_reactions.join(" ")} on the resend. The mapping ` +
            "is saved, you may need to react manually with those.",
          "error"
        );
      }
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setResendingId(null);
    }
  }

  return (
    <>
      <div className="card" ref={builderRef}>
        <h2>{editing ? "Edit reaction-role embed" : "Send a reaction-role embed"}</h2>
        <p className="muted small">
          Posts an embed in the channel you choose. Members react with one of the emojis below to get
          the matching role (and lose it if they remove their reaction).
        </p>
        <ReactionRoleBuilder guildId={guildId} roles={roles} channels={channels} onCreated={onChange}
                             editing={editing} onCancelEdit={() => setEditingMessageId(null)} />
      </div>
      <div className="card">
        <h2>Existing reaction-role messages</h2>
        {messages.length ? (
          <div className="rr-message-list">
            {messages.map((group) => (
              <div className={`rr-message-card ${group.message_id === editingMessageId ? "rr-message-card-editing" : ""}`}
                   key={group.message_id}>
                <div className="rr-message-head">
                  <div>
                    <div className="rr-message-channel">
                      #{channelNameById[group.channel_id] || group.channel_id}
                    </div>
                    <div className="muted small">
                      Message <code>{group.message_id}</code>
                    </div>
                  </div>
                  <div className="rr-message-actions">
                    <button
                      className="btn btn-ghost btn-small"
                      onClick={() => startEdit(group.message_id)}
                      disabled={deletingId === group.message_id || resendingId === group.message_id}
                    >
                      <Pencil size={13} /> Edit
                    </button>
                    <button
                      className="btn btn-ghost btn-small"
                      onClick={() => handleResend(group.message_id)}
                      disabled={resendingId === group.message_id || deletingId === group.message_id}
                      title="Post this as a new message (useful if the original was deleted)"
                    >
                      {resendingId === group.message_id ? <Spinner size={12} /> : <RefreshCw size={13} />}
                      Resend
                    </button>
                    <button
                      className="btn btn-ghost btn-small"
                      onClick={() => handleDeleteMessage(group.message_id)}
                      disabled={deletingId === group.message_id || resendingId === group.message_id}
                    >
                      {deletingId === group.message_id ? <Spinner size={12} /> : <Trash2 size={13} />}
                      Delete
                    </button>
                  </div>
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

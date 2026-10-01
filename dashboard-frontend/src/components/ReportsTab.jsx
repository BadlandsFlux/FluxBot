import { useEffect, useRef, useState } from "react";
import { CheckCircle2, XCircle, RotateCcw, Copy, Save, Search } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Combobox from "./Combobox";
import Spinner from "./Spinner";

const STATUS_TAG_CLASS = { open: "tag-warn", duplicate: "tag-purge", resolved: "tag-unban", wontfix: "tag-ban" };
const STATUS_LABEL = { open: "Open", duplicate: "Duplicate", resolved: "Resolved", wontfix: "Won't Fix" };
const CONTENT_PREVIEW_LENGTH = 140;

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function ReportsTab({ guildId, guild, channels, reports, onChange, onGuildChange }) {
  const flash = useFlash();
  const [filter, setFilter] = useState("open");
  const [query, setQuery] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [dupInputs, setDupInputs] = useState({});
  const [reportChannelId, setReportChannelId] = useState(guild.report_channel_id || "");
  const [trackerChannelId, setTrackerChannelId] = useState(guild.report_tracker_channel_id || "");
  const [savingChannels, setSavingChannels] = useState(false);
  const seenIds = useRef(null);

  // Surfaces the background 8s poll (see GuildDetail.jsx's usePolling) as
  // something a moderator actually notices: flashes once per batch of
  // report ids that weren't here last render. Skipped on first mount (no
  // baseline to diff against yet) and never false-fires off a report's own
  // status-change response, since that's still the same set of ids.
  useEffect(() => {
    const currentIds = new Set(reports.map((r) => r.id));
    if (seenIds.current) {
      const newCount = [...currentIds].filter((id) => !seenIds.current.has(id)).length;
      if (newCount > 0) {
        flash(`📝 ${newCount} new report${newCount > 1 ? "s" : ""} came in.`);
      }
    }
    seenIds.current = currentIds;
  }, [reports, flash]);

  const visible = reports
    .filter((r) => filter === "all" || r.status === filter)
    .filter((r) => !query.trim() || r.content.toLowerCase().includes(query.trim().toLowerCase()));

  async function updateStatus(reportId, status, extra = {}) {
    setBusyId(reportId);
    try {
      const result = await api.setReportStatus(guildId, reportId, { status, ...extra });
      onChange(result.reports);
      flash(`Report #${reportId} marked ${STATUS_LABEL[status].toLowerCase()}.`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setBusyId(null);
    }
  }

  function handleMarkDuplicate(reportId) {
    const of = Number(dupInputs[reportId]);
    if (!of) {
      flash("Enter the original report's number first.", "error");
      return;
    }
    updateStatus(reportId, "duplicate", { duplicate_of: of });
  }

  async function handleSaveChannels(e) {
    e.preventDefault();
    setSavingChannels(true);
    try {
      const result = await api.setReportChannels(guildId, {
        report_channel_id: reportChannelId || "",
        report_tracker_channel_id: trackerChannelId || "",
      });
      onGuildChange(result.guild);
      flash("Report channels saved.");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSavingChannels(false);
    }
  }

  return (
    <>
      <div className="card">
        <h2>Channels</h2>
        <p className="muted small">
          Any message posted in the report channel becomes a report, no command needed, and is always moved to the
          tracker channel below (set here or with <code>!reportchannel</code>/<code>!reporttracker</code>).
        </p>
        <form onSubmit={handleSaveChannels} className="settings-form">
          <label>
            Report channel
            <Combobox options={channels} value={reportChannelId} onChange={setReportChannelId}
                      placeholder="No report channel set" />
          </label>
          <label>
            Tracker channel
            <Combobox options={channels} value={trackerChannelId} onChange={setTrackerChannelId}
                      placeholder="Optional, but recommended" />
          </label>
          <button className="btn btn-primary btn-small" type="submit" disabled={savingChannels}>
            {savingChannels ? <Spinner size={14} /> : <Save size={14} />} Save
          </button>
        </form>
      </div>

      <div className="card">
        <h2>Bug/issue reports</h2>
        <p className="muted small">
          Set <code>Private: yes</code> in a report (see the channel explainer) to leave the reporter's name off
          the tracker entry below. Updates automatically as new reports come in.
        </p>

        <div className="filter-bar">
          <div className="search-box">
            <Search size={16} className="search-icon" />
            <input
              type="text"
              placeholder="Search report text…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All statuses</option>
            <option value="open">Open</option>
            <option value="duplicate">Duplicate</option>
            <option value="resolved">Resolved</option>
            <option value="wontfix">Won't Fix</option>
          </select>
        </div>

        {visible.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>Report</th>
                <th>Reporter</th>
                <th>Reported</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const preview = r.content.length > CONTENT_PREVIEW_LENGTH
                  ? `${r.content.slice(0, CONTENT_PREVIEW_LENGTH)}…`
                  : r.content;
                return (
                  <tr key={r.id}>
                    <td>#{r.id}</td>
                    <td>
                      <div className="report-status-cell">
                        <span className={`tag ${STATUS_TAG_CLASS[r.status]}`}>{STATUS_LABEL[r.status]}</span>
                        {r.duplicate_of ? (
                          <span className="tag tag-purge" title="Confirmed by staff">of #{r.duplicate_of}</span>
                        ) : null}
                        {r.status === "open" && r.possible_duplicate_of ? (
                          <span className="tag tag-kick" title="Auto-flagged, not confirmed">
                            ⚠️ like #{r.possible_duplicate_of}
                          </span>
                        ) : null}
                      </div>
                    </td>
                    <td className="muted small" title={r.content.length > CONTENT_PREVIEW_LENGTH ? r.content : undefined}>
                      {preview}
                    </td>
                    <td className="muted small">{r.reporter_username || "private"}</td>
                    <td className="muted small" title={r.created_at ? fmt(r.created_at) : undefined}>
                      {r.created_at ? fmt(r.created_at) : "?"}
                    </td>
                    <td>
                      <div className="member-actions">
                        {r.status !== "resolved" && (
                          <button className="btn btn-ghost btn-small" disabled={busyId === r.id}
                                  onClick={() => updateStatus(r.id, "resolved")}>
                            <CheckCircle2 size={14} /> Resolve
                          </button>
                        )}
                        {r.status !== "wontfix" && (
                          <button className="btn btn-ghost btn-small" disabled={busyId === r.id}
                                  onClick={() => updateStatus(r.id, "wontfix")}>
                            <XCircle size={14} /> Won't fix
                          </button>
                        )}
                        {r.status !== "open" && (
                          <button className="btn btn-ghost btn-small" disabled={busyId === r.id}
                                  onClick={() => updateStatus(r.id, "open")}>
                            <RotateCcw size={14} /> Reopen
                          </button>
                        )}
                        {r.status === "open" && (
                          <span className="report-dup-group">
                            <input
                              type="number"
                              placeholder="report #"
                              value={dupInputs[r.id] || ""}
                              onChange={(e) => setDupInputs((d) => ({ ...d, [r.id]: e.target.value }))}
                              style={{ width: 90 }}
                            />
                            <button className="btn btn-ghost btn-small" disabled={busyId === r.id}
                                    onClick={() => handleMarkDuplicate(r.id)}>
                              <Copy size={14} /> Mark duplicate
                            </button>
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="muted">No {filter === "all" ? "" : filter} reports{query.trim() ? " match that search" : ""}.</p>
        )}
      </div>
    </>
  );
}

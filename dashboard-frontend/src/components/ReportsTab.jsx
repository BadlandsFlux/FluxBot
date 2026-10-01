import { useState } from "react";
import { CheckCircle2, XCircle, RotateCcw, Copy } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";

const STATUS_TAG_CLASS = { open: "tag-warn", duplicate: "tag-purge", resolved: "tag-unban", wontfix: "tag-ban" };
const STATUS_LABEL = { open: "Open", duplicate: "Duplicate", resolved: "Resolved", wontfix: "Won't Fix" };

export default function ReportsTab({ guildId, reports, onChange }) {
  const flash = useFlash();
  const [filter, setFilter] = useState("open");
  const [busyId, setBusyId] = useState(null);
  const [dupInputs, setDupInputs] = useState({});

  const visible = filter === "all" ? reports : reports.filter((r) => r.status === filter);

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

  return (
    <div className="card">
      <h2>Bug/issue reports</h2>
      <p className="muted small">
        Captured automatically from the report channel configured in Settings, no command needed. Set a tracker
        channel there too so people can see what's already been reported before filing another one.
      </p>

      <div className="filter-bar">
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All reports</option>
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
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.id}>
                <td>#{r.id}</td>
                <td>
                  <span className={`tag ${STATUS_TAG_CLASS[r.status]}`}>{STATUS_LABEL[r.status]}</span>
                  {r.status === "open" && r.possible_duplicate_of && (
                    <div className="muted small">⚠️ like #{r.possible_duplicate_of}</div>
                  )}
                  {r.duplicate_of ? <div className="muted small">of #{r.duplicate_of}</div> : null}
                </td>
                <td className="muted small">{r.content}</td>
                <td className="muted small">{r.reporter_username || "private"}</td>
                <td>
                  <div className="member-actions">
                    {r.status !== "resolved" && (
                      <button className="btn btn-ghost btn-small btn-icon" title="Resolve" disabled={busyId === r.id}
                              onClick={() => updateStatus(r.id, "resolved")}>
                        <CheckCircle2 size={14} />
                      </button>
                    )}
                    {r.status !== "wontfix" && (
                      <button className="btn btn-ghost btn-small btn-icon" title="Won't fix" disabled={busyId === r.id}
                              onClick={() => updateStatus(r.id, "wontfix")}>
                        <XCircle size={14} />
                      </button>
                    )}
                    {r.status !== "open" && (
                      <button className="btn btn-ghost btn-small btn-icon" title="Reopen" disabled={busyId === r.id}
                              onClick={() => updateStatus(r.id, "open")}>
                        <RotateCcw size={14} />
                      </button>
                    )}
                    {r.status === "open" && (
                      <>
                        <input
                          type="number"
                          placeholder="dup of #"
                          value={dupInputs[r.id] || ""}
                          onChange={(e) => setDupInputs((d) => ({ ...d, [r.id]: e.target.value }))}
                          style={{ width: 80 }}
                        />
                        <button className="btn btn-ghost btn-small btn-icon" title="Mark duplicate"
                                disabled={busyId === r.id} onClick={() => handleMarkDuplicate(r.id)}>
                          <Copy size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No {filter === "all" ? "" : filter} reports.</p>
      )}
    </div>
  );
}

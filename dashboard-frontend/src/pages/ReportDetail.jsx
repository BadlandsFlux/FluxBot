import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Copy, RotateCcw, Send, XCircle } from "lucide-react";
import { api } from "../api";
import { useFlash } from "../components/Flash";
import Spinner from "../components/Spinner";
import usePolling from "../hooks/usePolling";

const STATUS_TAG_CLASS = { open: "tag-warn", duplicate: "tag-purge", resolved: "tag-unban", wontfix: "tag-ban" };
const STATUS_LABEL = { open: "Open", duplicate: "Duplicate", resolved: "Resolved", wontfix: "Won't Fix" };

function fmt(iso) {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function ReportDetail() {
  const { id, reportId } = useParams();
  const flash = useFlash();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dupInput, setDupInput] = useState("");
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const seenReplyIds = useRef(null);

  const load = useCallback(
    (silent = false) =>
      api
        .reportDetail(id, reportId)
        .then((d) => {
          setData(d);
          if (!silent) setError(null);
        })
        .catch((e) => !silent && setError(e.message)),
    [id, reportId]
  );

  useEffect(() => {
    setData(null);
    setError(null);
    seenReplyIds.current = null;
    load();
  }, [id, reportId, load]);

  // Same live-ish 8s poll every other page uses, so a reporter's DM reply
  // shows up here without a manual refresh.
  usePolling(() => load(true), 8000, !!data);

  // Mirrors ReportsTab's new-report toast: flashes once per batch of reply
  // ids that weren't here last render, skipped on first mount. A reply
  // staff just sent themselves is pre-seeded into seenReplyIds by
  // handleSendReply below before this ever runs, so sending one doesn't
  // also flash "new reply" about your own message.
  useEffect(() => {
    if (!data) return;
    const currentIds = new Set(data.replies.map((r) => r.id));
    if (seenReplyIds.current) {
      const newCount = [...currentIds].filter((rid) => !seenReplyIds.current.has(rid)).length;
      if (newCount > 0) flash(`💬 ${newCount} new repl${newCount > 1 ? "ies" : "y"} came in.`);
    }
    seenReplyIds.current = currentIds;
  }, [data, flash]);

  async function updateStatus(status, extra = {}) {
    setBusy(true);
    try {
      const result = await api.setReportStatus(id, reportId, { status, ...extra });
      const updated = result.reports.find((r) => r.id === Number(reportId));
      setData((d) => (updated ? { ...d, report: updated } : d));
      flash(`Report #${reportId} marked ${STATUS_LABEL[status].toLowerCase()}.`);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function handleMarkDuplicate() {
    const of = Number(dupInput);
    if (!of) {
      flash("Enter the original report's number first.", "error");
      return;
    }
    updateStatus("duplicate", { duplicate_of: of });
  }

  async function handleSendReply(e) {
    e.preventDefault();
    const content = replyText.trim();
    if (!content) return;
    setSending(true);
    try {
      const result = await api.addReportReply(id, reportId, content);
      seenReplyIds.current = new Set(result.replies.map((r) => r.id));
      setData(result);
      setReplyText("");
      flash(
        result.delivered ? "Reply sent." : "Reply saved, but I couldn't DM the reporter (they may have DMs closed).",
        result.delivered ? "success" : "error"
      );
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSending(false);
    }
  }

  if (error) {
    return (
      <div className="card empty-state">
        <p className="error">{error}</p>
        <Link className="btn btn-ghost btn-small" to={`/guild/${id}?tab=reports`}>
          ← Back to reports
        </Link>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="loading-row">
        <Spinner />
        <span className="muted">Loading report…</span>
      </div>
    );
  }

  const { report, replies } = data;

  return (
    <div>
      <Link className="back-link" to={`/guild/${id}?tab=reports`}>
        <ArrowLeft size={13} /> Back to reports
      </Link>

      <div className="card">
        <div className="report-detail-head">
          <h1>Report #{report.id}</h1>
          <div className="report-status-cell">
            <span className={`tag ${STATUS_TAG_CLASS[report.status]}`}>{STATUS_LABEL[report.status]}</span>
            {report.duplicate_of ? (
              <span className="tag tag-purge" title="Confirmed by staff">of #{report.duplicate_of}</span>
            ) : null}
            {report.status === "open" && report.possible_duplicate_of ? (
              <span className="tag tag-kick" title="Auto-flagged, not confirmed">
                ⚠️ like #{report.possible_duplicate_of}
              </span>
            ) : null}
          </div>
        </div>
        <p className="muted small">
          Reported by {report.reporter_username || "a private reporter"} · {fmt(report.created_at)}
        </p>
        <p className="report-detail-content">{report.content}</p>
        {report.resolution_note && (
          <p className="muted small">
            <strong>Note from staff:</strong> {report.resolution_note}
          </p>
        )}

        <div className="member-actions" style={{ marginTop: 16 }}>
          {report.status !== "resolved" && (
            <button className="btn btn-ghost btn-small" disabled={busy} onClick={() => updateStatus("resolved")}>
              <CheckCircle2 size={14} /> Resolve
            </button>
          )}
          {report.status !== "wontfix" && (
            <button className="btn btn-ghost btn-small" disabled={busy} onClick={() => updateStatus("wontfix")}>
              <XCircle size={14} /> Won't fix
            </button>
          )}
          {report.status !== "open" && (
            <button className="btn btn-ghost btn-small" disabled={busy} onClick={() => updateStatus("open")}>
              <RotateCcw size={14} /> Reopen
            </button>
          )}
          {report.status === "open" && (
            <span className="report-dup-group">
              <input
                type="number"
                placeholder="report #"
                value={dupInput}
                onChange={(e) => setDupInput(e.target.value)}
                style={{ width: 90 }}
              />
              <button className="btn btn-ghost btn-small" disabled={busy} onClick={handleMarkDuplicate}>
                <Copy size={14} /> Mark duplicate
              </button>
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <h2>Conversation</h2>
        <p className="muted small">
          Replies DM the reporter, and they can DM back the same way, no command needed on their end.
        </p>

        {replies.length === 0 ? (
          <p className="muted">No replies yet, send one below to start a conversation with the reporter.</p>
        ) : (
          <div className="reply-thread">
            {replies.map((r) => (
              <div className={`reply-item reply-item-${r.author_type}`} key={r.id}>
                <div className="reply-meta">
                  <span className="reply-author">
                    {r.author_type === "staff" ? r.author_username || "Staff" : r.author_username || "Reporter"}
                  </span>
                  <span className="muted small">{fmt(r.created_at)}</span>
                </div>
                <div className="reply-content">{r.content}</div>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={handleSendReply} className="settings-form reply-compose">
          <textarea
            rows={3}
            placeholder="Reply to the reporter…"
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
          />
          <button className="btn btn-primary btn-small" type="submit" disabled={sending || !replyText.trim()}>
            {sending ? <Spinner size={14} /> : <Send size={14} />} Send reply
          </button>
        </form>
      </div>
    </div>
  );
}

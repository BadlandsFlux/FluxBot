import { useEffect, useState } from "react";
import { Newspaper } from "lucide-react";
import { api } from "../api";
import { useFlash } from "../components/Flash";
import Spinner from "../components/Spinner";

function toTimeString(hour, minute) {
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export default function FluxerPatchNotes() {
  const flash = useFlash();
  const [time, setTime] = useState("00:05");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getFluxerPatchNotesConfig()
      .then((cfg) => setTime(toTimeString(cfg.trigger_hour, cfg.trigger_minute)))
      .catch((e) => flash(e.message, "error"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load once on mount
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    const [hourStr, minuteStr] = time.split(":");
    setSaving(true);
    try {
      await api.setFluxerPatchNotesConfig({
        trigger_hour: Number(hourStr),
        trigger_minute: Number(minuteStr),
      });
      flash("Saved.");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h2>
        <Newspaper size={18} /> Fluxer patch notes
      </h2>
      <p className="muted small">
        Owner-only, bot-wide. Once a day, the bot fetches that day's commits to{" "}
        <a href="https://github.com/fluxerapp/fluxer" target="_blank" rel="noreferrer">fluxerapp/fluxer</a>'s
        main branch, groups them by feature/fix/maintenance, and posts the digest to any server that's picked a
        channel for it (on that server's own Settings tab). This only controls when it's sent, always for the
        full day that just ended in Central time, never a partial day still in progress.
      </p>

      {loading ? (
        <Spinner size={18} />
      ) : (
        <form onSubmit={handleSubmit} className="settings-form">
          <label>
            Send time (Central time)
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
          </label>
          <button className="btn btn-primary btn-small" type="submit" disabled={saving}>
            {saving ? <Spinner size={14} /> : null}
            {saving ? "Saving…" : "Save"}
          </button>
        </form>
      )}
    </div>
  );
}

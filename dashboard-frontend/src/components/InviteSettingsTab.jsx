import { useEffect, useState } from "react";
import { Link2, Copy } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";

export default function InviteSettingsTab() {
  const flash = useFlash();
  const [data, setData] = useState(null);
  const [permissionsInput, setPermissionsInput] = useState("");
  const [saving, setSaving] = useState(false);

  function load() {
    api
      .inviteSettings()
      .then((d) => {
        setData(d);
        setPermissionsInput(String(d.permissions));
      })
      .catch((e) => flash(e.message, "error"));
  }

  useEffect(load, []);

  async function handleSave(e) {
    e.preventDefault();
    const permissions = Number(permissionsInput);
    if (!Number.isInteger(permissions) || permissions < 0) {
      flash("Permissions must be a non-negative whole number.", "error");
      return;
    }
    setSaving(true);
    try {
      const result = await api.setInvitePermissions(permissions);
      setData((prev) => ({ ...prev, invite_url: result.invite_url, permissions }));
      flash("Saved.");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSaving(false);
    }
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(data.invite_url);
      flash("Copied.");
    } catch {
      flash("Couldn't copy, select and copy the link manually.", "error");
    }
  }

  if (!data) {
    return (
      <div className="card loading-row">
        <Spinner />
        <span className="muted">Loading…</span>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>
        <Link2 size={18} /> Invite link
      </h2>
      <p className="muted small">
        Owner-only. Controls the link shown to any logged-in user on the server picker and the server switcher,
        for adding this bot to another server of theirs.
      </p>

      {!data.invite_url ? (
        <p className="muted small">
          <code>FLUXER_OAUTH_CLIENT_ID</code> isn't set, so there's nothing to build an invite link from yet, it's
          the same application this dashboard's own login already uses. Add it to your <code>.env</code> (see{" "}
          <code>.env.example</code>), then come back here to set the permissions it should request.
        </p>
      ) : (
        <>
          <form onSubmit={handleSave} className="inline-form">
            <input
              type="number"
              min="0"
              step="1"
              placeholder="Permissions bitmask, e.g. 8 for Administrator"
              value={permissionsInput}
              onChange={(e) => setPermissionsInput(e.target.value)}
              style={{ flex: 1 }}
            />
            <button className="btn btn-primary btn-small" type="submit" disabled={saving}>
              {saving ? <Spinner size={14} /> : "Save"}
            </button>
          </form>
          <p className="muted small">
            The permissions value a server owner is asked to grant when they click the link, same bitmask Discord
            bots use. 0 requests no elevated permissions at all.
          </p>

          <div className="inline-form">
            <input type="text" readOnly value={data.invite_url} style={{ flex: 1 }} onFocus={(e) => e.target.select()} />
            <button type="button" className="btn btn-ghost btn-small" onClick={handleCopy}>
              <Copy size={14} /> Copy
            </button>
          </div>
        </>
      )}
    </div>
  );
}

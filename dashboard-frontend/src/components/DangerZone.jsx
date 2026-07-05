import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";

const ACTIONS = [
  {
    key: "clear-warnings",
    label: "Clear all warnings",
    description: "Deactivates every active warning for every member, server-wide. Warning history stays visible in Mod Log, just no longer counts toward escalation.",
    confirmText: "This deactivates every active warning on this server. This can't be undone. Type CONFIRM to proceed.",
    run: (guildId) => api.dangerClearAllWarnings(guildId),
    resultText: (r) => `Cleared ${r.cleared} active warning(s).`,
  },
  {
    key: "reset-xp",
    label: "Reset all XP and levels",
    description: "Wipes every member's level and XP back to zero. Message/voice activity stats are untouched, this only affects leveling.",
    confirmText: "This resets every member's level and XP to zero, permanently. Type CONFIRM to proceed.",
    run: (guildId) => api.dangerResetAllXp(guildId),
    resultText: (r) => `Reset XP for ${r.reset} member(s).`,
  },
  {
    key: "wipe-reaction-roles",
    label: "Wipe all reaction roles",
    description: "Deletes every reaction-role mapping. The original messages in Fluxer aren't deleted, they'll just stop granting roles when reacted to.",
    confirmText: "This deletes every reaction-role mapping on this server, permanently. Type CONFIRM to proceed.",
    run: (guildId) => api.dangerWipeReactionRoles(guildId),
    resultText: (r) => `Wiped ${r.wiped} reaction-role mapping(s).`,
  },
];

export default function DangerZone({ guildId, onWarningsCleared, onReactionRolesWiped }) {
  const flash = useFlash();
  const [openKey, setOpenKey] = useState(null);
  const [confirmInput, setConfirmInput] = useState("");
  const [submitting, setSubmitting] = useState(null);

  function open(key) {
    setOpenKey(key);
    setConfirmInput("");
  }

  async function run(action) {
    setSubmitting(action.key);
    try {
      const result = await action.run(guildId);
      flash(action.resultText(result));
      if (action.key === "wipe-reaction-roles") onReactionRolesWiped?.();
      if (action.key === "clear-warnings") onWarningsCleared?.();
      setOpenKey(null);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="card danger-zone">
      <h2>
        <AlertTriangle size={18} /> Danger Zone
      </h2>
      <p className="muted small">
        Bulk, irreversible actions. Each requires typing CONFIRM before it runs.
      </p>
      <div className="danger-actions">
        {ACTIONS.map((action) => (
          <div className="danger-action-row" key={action.key}>
            <div>
              <div className="danger-action-label">{action.label}</div>
              <div className="muted small">{action.description}</div>
            </div>
            {openKey === action.key ? (
              <div className="danger-confirm-panel">
                <p className="small">{action.confirmText}</p>
                <div className="danger-confirm-controls">
                  <input
                    type="text"
                    placeholder="Type CONFIRM"
                    value={confirmInput}
                    onChange={(e) => setConfirmInput(e.target.value)}
                    autoFocus
                  />
                  <button
                    className="btn btn-danger btn-small"
                    disabled={confirmInput !== "CONFIRM" || submitting === action.key}
                    onClick={() => run(action)}
                  >
                    {submitting === action.key ? <Spinner size={12} /> : "Run it"}
                  </button>
                  <button className="btn btn-ghost btn-small" onClick={() => setOpenKey(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button className="btn btn-ghost btn-small" onClick={() => open(action.key)}>
                Run
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

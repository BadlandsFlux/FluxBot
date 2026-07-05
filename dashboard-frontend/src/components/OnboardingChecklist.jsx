import { useState } from "react";
import { CheckCircle2, Circle, X } from "lucide-react";

function storageKey(guildId) {
  return `fluxbot-onboarding-dismissed-${guildId}`;
}

export default function OnboardingChecklist({ guild, autoroles, reactionRoles, tags, setTab }) {
  const [closedThisSession, setClosedThisSession] = useState(false);
  const [neverRemind, setNeverRemind] = useState(
    () => localStorage.getItem(storageKey(guild.guild_id)) === "1"
  );

  const items = [
    {
      key: "modlog",
      label: "Mod-log channel set",
      done: !!guild.log_channel_id,
      tab: "settings",
    },
    {
      key: "welcome",
      label: "Welcome message configured",
      done: !!guild.welcome_channel_id,
      tab: "settings",
    },
    {
      key: "goodbye",
      label: "Goodbye message configured",
      done: !!guild.goodbye_channel_id,
      tab: "settings",
    },
    {
      key: "autoroles",
      label: "At least one autorole set up",
      done: autoroles.length > 0,
      tab: "autoroles",
    },
    {
      key: "reactionroles",
      label: "At least one reaction-role message",
      done: reactionRoles.length > 0,
      tab: "reactionroles",
    },
    {
      key: "leveling",
      label: "Leveling turned on",
      done: !!guild.leveling_enabled,
      tab: "settings",
    },
    {
      key: "tags",
      label: "At least one custom tag",
      done: tags.length > 0,
      tab: "tags",
    },
  ];

  const doneCount = items.filter((i) => i.done).length;
  if (doneCount === items.length || closedThisSession || neverRemind) return null;

  function dismissForever() {
    localStorage.setItem(storageKey(guild.guild_id), "1");
    setNeverRemind(true);
  }

  return (
    <div className="card onboarding-checklist">
      <button type="button" className="onboarding-close" onClick={() => setClosedThisSession(true)} title="Close">
        <X size={16} />
      </button>
      <h2>Getting set up ({doneCount}/{items.length})</h2>
      <p className="muted small">A quick look at what's configured so far. Disappears once everything below is done.</p>
      <ul className="checklist">
        {items.map((item) => (
          <li key={item.key} className={item.done ? "checklist-done" : ""}>
            <button type="button" className="checklist-item-btn" onClick={() => setTab(item.tab)}>
              {item.done ? <CheckCircle2 size={16} className="checklist-icon-done" /> : <Circle size={16} className="checklist-icon-todo" />}
              <span>{item.label}</span>
            </button>
          </li>
        ))}
      </ul>
      <button type="button" className="onboarding-never-remind" onClick={dismissForever}>
        Don't remind me again
      </button>
    </div>
  );
}

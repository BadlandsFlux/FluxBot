import { CheckCircle2, Circle } from "lucide-react";

export default function OnboardingChecklist({ guild, autoroles, reactionRoles, tags, setTab }) {
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
  if (doneCount === items.length) return null; // fully set up, don't clutter the page

  return (
    <div className="card onboarding-checklist">
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
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { api } from "../api";
import { useFlash } from "./Flash";
import Spinner from "./Spinner";
import Switch from "./Switch";

const CATEGORY_ORDER = ["Moderation", "Roles", "Info", "Fun", "Utility", "General"];

export default function CommandsTab({ guildId }) {
  const flash = useFlash();
  const [data, setData] = useState(null);
  const [query, setQuery] = useState("");

  function load() {
    api
      .guildCommands(guildId)
      .then(setData)
      .catch((e) => flash(e.message, "error"));
  }

  useEffect(load, [guildId]);

  async function handleToggle(name, enabled) {
    try {
      await (enabled ? api.enableCommand(guildId, name) : api.disableCommand(guildId, name));
      setData((d) => {
        const categories = {};
        for (const [category, cmds] of Object.entries(d.categories)) {
          categories[category] = cmds.map((c) => (c.name === name ? { ...c, enabled } : c));
        }
        return { ...d, categories };
      });
    } catch (err) {
      flash(err.message, "error");
    }
  }

  const filtered = useMemo(() => {
    if (!data) return {};
    const q = query.trim().toLowerCase();
    const out = {};
    for (const [category, cmds] of Object.entries(data.categories)) {
      const kept = q
        ? cmds.filter(
            (c) =>
              c.name.toLowerCase().includes(q) ||
              (c.help_text || "").toLowerCase().includes(q) ||
              c.aliases.some((a) => a.toLowerCase().includes(q))
          )
        : cmds;
      if (kept.length) out[category] = kept;
    }
    return out;
  }, [data, query]);

  if (!data) {
    return (
      <div className="card loading-row">
        <Spinner />
        <span className="muted">Loading…</span>
      </div>
    );
  }

  const categories = [
    ...CATEGORY_ORDER.filter((c) => c in filtered),
    ...Object.keys(filtered).filter((c) => !CATEGORY_ORDER.includes(c)),
  ];

  return (
    <>
      <div className="card">
        <h2>Commands</h2>
        <p className="muted small">
          Turn off any command just for this server. Disabled commands reply as if they don't exist here, everyone
          else is unaffected. A couple of commands are always on, so the server can't lock itself out of managing
          this list.
        </p>
      </div>

      <div className="search-box">
        <Search size={16} className="search-icon" />
        <input
          type="text"
          placeholder="Search commands…"
          aria-label="Search commands"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {categories.length === 0 && (
        <div className="card empty-state">
          <p className="muted">No commands match "{query}".</p>
        </div>
      )}

      {categories.map((category) => (
        <div className="card" key={category}>
          <h2>{category}</h2>
          <div className="cmd-list">
            {filtered[category].map((cmd) => (
              <div className={`cmd-row ${!cmd.enabled ? "cmd-row-disabled" : ""}`} key={cmd.name}>
                <div className="cmd-name">
                  <code>{cmd.name}</code>
                  {cmd.aliases.length > 0 && <span className="muted small"> ({cmd.aliases.join(", ")})</span>}
                </div>
                <div className="cmd-desc">{cmd.help_text || "No description."}</div>
                <div className="cmd-perm-toggle">
                  <span className={`tag ${cmd.permission === "Everyone" ? "tag-unban" : "tag-warn"}`}>
                    {cmd.permission}
                  </span>
                  {cmd.locked ? (
                    <span className="muted small" title="This command can't be disabled">
                      Always on
                    </span>
                  ) : (
                    <Switch checked={cmd.enabled} onChange={(v) => handleToggle(cmd.name, v)} />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

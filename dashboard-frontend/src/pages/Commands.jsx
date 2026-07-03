import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { api } from "../api";
import Spinner from "../components/Spinner";

const CATEGORY_ORDER = ["Moderation", "Roles", "Info", "Fun", "Utility", "General"];

export default function Commands() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.commands().then(setData).catch((e) => setError(e.message));
  }, []);

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

  if (error) {
    return (
      <div className="card empty-state">
        <p className="error">{error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="loading-row">
        <Spinner />
        <span className="muted">Loading commands…</span>
      </div>
    );
  }

  const categories = [
    ...CATEGORY_ORDER.filter((c) => c in filtered),
    ...Object.keys(filtered).filter((c) => !CATEGORY_ORDER.includes(c)),
  ];

  return (
    <>
      <div className="page-head">
        <h1>Commands</h1>
        <p className="muted">
          Default prefix is <code>{data.default_prefix}</code> — servers can change this from their Settings tab.
        </p>
      </div>

      <div className="search-box">
        <Search size={16} className="search-icon" />
        <input
          type="text"
          placeholder="Search commands…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
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
              <div className="cmd-row" key={cmd.name}>
                <div className="cmd-name">
                  <code>
                    {data.default_prefix}
                    {cmd.name}
                  </code>
                  {cmd.aliases.length > 0 && <span className="muted small"> ({cmd.aliases.join(", ")})</span>}
                </div>
                <div className="cmd-desc">{cmd.help_text || "No description."}</div>
                <div className="cmd-perm">
                  <span className={`tag ${cmd.permission === "Everyone" ? "tag-unban" : "tag-warn"}`}>
                    {cmd.permission}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

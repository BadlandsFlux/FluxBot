import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, Search } from "lucide-react";
import { useGuilds } from "../context/GuildsContext";

export default function GuildSwitcher() {
  const location = useLocation();
  const navigate = useNavigate();
  const { guilds } = useGuilds();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef(null);

  const match = location.pathname.match(/^\/guild\/([^/]+)/);
  const currentId = match ? match[1] : null;
  const current = guilds.find((g) => g.id === currentId);

  useEffect(() => {
    function onClickOutside(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  if (!currentId) return null;

  const filtered = query.trim()
    ? guilds.filter((g) => g.name.toLowerCase().includes(query.trim().toLowerCase()))
    : guilds;

  return (
    <div className="guild-switcher" ref={rootRef}>
      <button type="button" className="guild-switcher-trigger" onClick={() => setOpen((v) => !v)}>
        {current?.icon_url ? (
          <img src={current.icon_url} alt="" className="guild-switcher-icon" />
        ) : (
          <span className="guild-switcher-icon guild-switcher-icon-fallback">
            {(current?.name || "?")[0].toUpperCase()}
          </span>
        )}
        <span className="guild-switcher-name">{current?.name || "Loading…"}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="guild-switcher-panel">
          <div className="guild-switcher-search">
            <Search size={13} />
            <input
              type="text"
              placeholder="Switch server…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              autoFocus
            />
          </div>
          <div className="guild-switcher-list">
            {filtered.length === 0 && <div className="combobox-empty">No matches.</div>}
            {filtered.map((g) => (
              <button
                type="button"
                key={g.id}
                className={`guild-switcher-option ${g.id === currentId ? "selected" : ""}`}
                onClick={() => {
                  setOpen(false);
                  setQuery("");
                  navigate(`/guild/${g.id}`);
                }}
              >
                {g.icon_url ? (
                  <img src={g.icon_url} alt="" className="guild-switcher-icon" />
                ) : (
                  <span className="guild-switcher-icon guild-switcher-icon-fallback">
                    {g.name[0].toUpperCase()}
                  </span>
                )}
                {g.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

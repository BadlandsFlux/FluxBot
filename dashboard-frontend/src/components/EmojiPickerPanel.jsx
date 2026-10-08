import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

const RECENT_KEY = "fluxbot-recent-emoji";
const RECENT_MAX = 24;

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveRecent(emoji) {
  try {
    const next = [emoji, ...loadRecent().filter((e) => e !== emoji)].slice(0, RECENT_MAX);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // best-effort only (private browsing, quota, etc.) -- recents are a
    // convenience, not something worth surfacing an error for.
  }
}

/**
 * Shared dropdown content for picking an emoji: the server's own custom
 * emoji (fetched from Fluxer when `guildId` is given), a recently-used
 * row, and the full standard Unicode set, searchable and grouped.
 *
 * `mode` decides which string a guild custom emoji pick resolves to:
 * "reaction" (the exact `name:id` form Fluxer's reaction endpoints
 * require) for a single-value field like a reaction-role row, or "text"
 * (the `<:name:id>` / `<a:name:id>` inline form) for inserting into
 * message content. Fluxer's docs confirm the reaction form but don't
 * specify a message-text tag syntax, so "text" follows the same
 * Discord-style convention this codebase already assumes elsewhere when
 * Fluxer's reference is silent (see dashboard/app.py's api_guild_emojis).
 */
export default function EmojiPickerPanel({ guildId, mode = "reaction", onPick }) {
  const [query, setQuery] = useState("");
  const [guildEmojis, setGuildEmojis] = useState([]);
  const [loadingGuildEmojis, setLoadingGuildEmojis] = useState(false);
  const [recent, setRecent] = useState(loadRecent);
  // The ~400KB standard-emoji dataset is only ever needed once this panel
  // actually renders (it's always inside an `open &&` dropdown), so it's
  // dynamically imported here rather than statically -- otherwise it'd
  // sit in every page's main bundle whether anyone opens a picker or not.
  const [groups, setGroups] = useState(null);

  useEffect(() => {
    let cancelled = false;
    import("unicode-emoji-json/data-by-group.json").then((mod) => {
      if (!cancelled) setGroups(mod.default);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!guildId) return undefined;
    let cancelled = false;
    setLoadingGuildEmojis(true);
    api
      .guildEmojis(guildId)
      .then((data) => {
        if (!cancelled) setGuildEmojis(data.emojis || []);
      })
      .catch(() => {
        // Best-effort: the standard emoji grid below still works fine
        // without the server's custom emoji.
      })
      .finally(() => {
        if (!cancelled) setLoadingGuildEmojis(false);
      });
    return () => {
      cancelled = true;
    };
  }, [guildId]);

  const needle = query.trim().toLowerCase();
  const filteredGroups = useMemo(() => {
    if (!groups) return [];
    if (!needle) return groups;
    return groups
      .map((g) => ({ ...g, emojis: g.emojis.filter((e) => e.name.includes(needle) || e.slug.includes(needle)) }))
      .filter((g) => g.emojis.length > 0);
  }, [groups, needle]);

  const filteredGuildEmojis = needle
    ? guildEmojis.filter((e) => e.name.toLowerCase().includes(needle))
    : guildEmojis;

  function pickUnicode(emoji) {
    saveRecent(emoji);
    setRecent(loadRecent());
    onPick(emoji);
  }

  function pickGuildEmoji(emoji) {
    onPick(mode === "text" ? emoji.tag : emoji.reaction);
  }

  const nothingFound = needle && groups && filteredGroups.length === 0 && filteredGuildEmojis.length === 0;

  return (
    <div className="emoji-panel">
      <input
        type="text"
        className="emoji-panel-search"
        placeholder="Search emoji…"
        aria-label="Search emoji"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        autoFocus
      />
      <div className="emoji-panel-scroll">
        {!needle && recent.length > 0 && (
          <div className="emoji-panel-section">
            <div className="emoji-panel-section-title">Recently used</div>
            <div className="emoji-panel-grid">
              {recent.map((e) => (
                <button type="button" key={e} className="emoji-panel-cell" onClick={() => pickUnicode(e)} title={e}>
                  {e}
                </button>
              ))}
            </div>
          </div>
        )}
        {guildId && (loadingGuildEmojis || filteredGuildEmojis.length > 0) && (
          <div className="emoji-panel-section">
            <div className="emoji-panel-section-title">This server</div>
            {loadingGuildEmojis ? (
              <div className="muted small">Loading…</div>
            ) : (
              <div className="emoji-panel-grid">
                {filteredGuildEmojis.map((e) => (
                  <button
                    type="button"
                    key={e.id}
                    className="emoji-panel-cell emoji-panel-cell-custom"
                    onClick={() => pickGuildEmoji(e)}
                    title={`:${e.name}:`}
                  >
                    <img src={e.url} alt={e.name} loading="lazy" />
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {!groups && <div className="muted small emoji-panel-empty">Loading emoji…</div>}
        {filteredGroups.map((g) => (
          <div className="emoji-panel-section" key={g.slug}>
            <div className="emoji-panel-section-title">{g.name}</div>
            <div className="emoji-panel-grid">
              {g.emojis.map((e) => (
                <button
                  type="button"
                  key={e.slug}
                  className="emoji-panel-cell"
                  onClick={() => pickUnicode(e.emoji)}
                  title={e.name}
                >
                  {e.emoji}
                </button>
              ))}
            </div>
          </div>
        ))}
        {nothingFound && <div className="emoji-panel-empty muted small">No emoji match &ldquo;{query}&rdquo;.</div>}
      </div>
    </div>
  );
}

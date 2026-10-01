import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";

/**
 * A searchable dropdown. `options` is [{id, name, ...}]. `value` is an id
 * string (or ""). Falls back gracefully to showing the raw id if it's not
 * found in `options` (e.g. a role from a channel type the picker excluded,
 * or one that no longer exists), never silently drops the stored value.
 *
 * Closes immediately on selection, and briefly flashes the trigger so the
 * change is obvious even though the panel disappears right away.
 */
export default function Combobox({ options, value, onChange, placeholder = "Search…", allowClear = true }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [flash, setFlash] = useState(false);
  const rootRef = useRef(null);
  const isFirstRender = useRef(true);

  useEffect(() => {
    function onClickOutside(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setFlash(true);
    const t = setTimeout(() => setFlash(false), 500);
    return () => clearTimeout(t);
  }, [value]);

  function selectOption(id) {
    onChange(id);
    setOpen(false);
    setQuery("");
  }

  const selected = options.find((o) => o.id === value);
  const filtered = query.trim()
    ? options.filter((o) => o.name.toLowerCase().includes(query.trim().toLowerCase()))
    : options;

  return (
    <div className="combobox" ref={rootRef}>
      <button
        type="button"
        className={`combobox-trigger ${flash ? "combobox-trigger-flash" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={selected ? "" : "muted"}>
          {selected ? selected.name : value ? `Unknown (${value})` : placeholder}
        </span>
        <span className="combobox-trigger-icons">
          <ChevronDown size={14} />
        </span>
      </button>
      {allowClear && value && (
        // A sibling of the trigger, not nested inside it: a <button> inside
        // another <button> is invalid HTML (browsers silently hoist it back
        // out, breaking both the layout and the click handling), which is
        // also why this couldn't just become a real, keyboard-reachable
        // button without moving it out here in the first place.
        <button
          type="button"
          className="combobox-clear"
          aria-label="Clear selection"
          onClick={(e) => {
            e.stopPropagation();
            onChange("");
          }}
        >
          <X size={13} />
        </button>
      )}
      {open && (
        <div className="combobox-panel">
          <input
            type="text"
            className="combobox-search"
            placeholder="Type to filter…"
            aria-label="Filter options"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setOpen(false);
            }}
            autoFocus
          />
          <div className="combobox-list" role="listbox">
            {filtered.length === 0 && <div className="combobox-empty">No matches.</div>}
            {filtered.map((o) => (
              <button
                type="button"
                key={o.id}
                role="option"
                aria-selected={o.id === value}
                className={`combobox-option ${o.id === value ? "selected" : ""}`}
                onClick={() => selectOption(o.id)}
              >
                {o.color !== undefined && o.color !== null && o.color !== 0 && (
                  <span className="combobox-swatch" style={{ background: `#${o.color.toString(16).padStart(6, "0")}` }} />
                )}
                {o.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

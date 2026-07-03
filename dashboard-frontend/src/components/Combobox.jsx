import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";

/**
 * A searchable dropdown. `options` is [{id, name, ...}]. `value` is an id
 * string (or ""). Falls back gracefully to showing the raw id if it's not
 * found in `options` (e.g. a role from a channel type the picker excluded,
 * or one that no longer exists) — never silently drops the stored value.
 */
export default function Combobox({ options, value, onChange, placeholder = "Search…", allowClear = true }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const selected = options.find((o) => o.id === value);
  const filtered = query.trim()
    ? options.filter((o) => o.name.toLowerCase().includes(query.trim().toLowerCase()))
    : options;

  return (
    <div className="combobox" ref={rootRef}>
      <button type="button" className="combobox-trigger" onClick={() => setOpen((v) => !v)}>
        <span className={selected ? "" : "muted"}>
          {selected ? selected.name : value ? `Unknown (${value})` : placeholder}
        </span>
        <span className="combobox-trigger-icons">
          {allowClear && value && (
            <span
              className="combobox-clear"
              onClick={(e) => {
                e.stopPropagation();
                onChange("");
              }}
            >
              <X size={13} />
            </span>
          )}
          <ChevronDown size={14} />
        </span>
      </button>
      {open && (
        <div className="combobox-panel">
          <input
            type="text"
            className="combobox-search"
            placeholder="Type to filter…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          <div className="combobox-list">
            {filtered.length === 0 && <div className="combobox-empty">No matches.</div>}
            {filtered.map((o) => (
              <button
                type="button"
                key={o.id}
                className={`combobox-option ${o.id === value ? "selected" : ""}`}
                onClick={() => {
                  onChange(o.id);
                  setOpen(false);
                  setQuery("");
                }}
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

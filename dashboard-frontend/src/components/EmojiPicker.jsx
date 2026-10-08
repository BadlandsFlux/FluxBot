import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import EmojiPickerPanel from "./EmojiPickerPanel";

// `value` here is a single exact string (a reaction-role row's emoji),
// so a pick always replaces it outright. `guildId`, when given, adds
// the server's own custom emoji to the panel alongside the standard set.
export default function EmojiPicker({ value, onChange, guildId }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  const rootRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function pick(emoji) {
    onChange(emoji);
    // Deferred, not called synchronously here: removing the clicked
    // button's own panel in direct response to its own click, within
    // the same event-handling tick, triggers a real Chromium quirk --
    // the browser's focus manager, on finding the active element gone,
    // can synthesize a phantom follow-up click (detail: 0) elsewhere on
    // the page. Closing on the next tick lets the browser finish its
    // own click bookkeeping first. See EmojiInsertButton.jsx, where this
    // was first caught corrupting unrelated form state.
    setTimeout(() => setOpen(false), 0);
    setCustom("");
  }

  return (
    <div className="emoji-picker" ref={rootRef}>
      <button type="button" className="emoji-picker-trigger" onClick={() => setOpen((v) => !v)}>
        <span className={value ? "emoji-picker-value" : "muted"}>{value || "Pick"}</span>
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className="emoji-picker-panel">
          <EmojiPickerPanel guildId={guildId} mode="reaction" onPick={pick} />
          <div className="emoji-picker-custom">
            <input
              type="text"
              placeholder="Or paste a custom emoji"
              value={custom}
              onChange={(e) => setCustom(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && custom.trim()) {
                  e.preventDefault();
                  pick(custom.trim());
                }
              }}
            />
            <button
              type="button"
              className="btn btn-ghost btn-small"
              onClick={() => custom.trim() && pick(custom.trim())}
            >
              Use
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

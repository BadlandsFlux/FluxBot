import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

const COMMON_EMOJI = [
  "😀", "😂", "😍", "🥳", "😎", "🤔", "😭", "😡", "👍", "👎",
  "❤️", "🔥", "🎉", "🎮", "🎵", "🎨", "📚", "⚽", "🏆", "🍕",
  "☕", "🌟", "✅", "❌", "🔔", "💡", "🚀", "🎯", "🌈", "⭐",
  "💯", "🙌", "👋", "🎁", "🐱", "🐶", "🌸", "☀️", "🌙", "⚡",
];

export default function EmojiPicker({ value, onChange }) {
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
    setOpen(false);
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
          <div className="emoji-picker-grid">
            {COMMON_EMOJI.map((e) => (
              <button
                type="button"
                key={e}
                className={`emoji-picker-cell ${value === e ? "selected" : ""}`}
                onClick={() => pick(e)}
                title={e}
              >
                {e}
              </button>
            ))}
          </div>
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

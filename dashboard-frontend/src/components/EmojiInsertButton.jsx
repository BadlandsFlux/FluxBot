import { useEffect, useRef, useState } from "react";
import { Smile } from "lucide-react";
import EmojiPickerPanel from "./EmojiPickerPanel";

// Inserts at the cursor rather than replacing the whole field, so it
// works the same way the other formatting buttons in MarkdownToolbar do.
// Works for both <textarea> and single-line <input> refs -- both support
// selectionStart/selectionEnd/setSelectionRange the same way.
function insertAtCursor(target, value, onChange, text) {
  const start = target.selectionStart ?? value.length;
  const end = target.selectionEnd ?? value.length;
  const next = value.slice(0, start) + text + value.slice(end);
  onChange(next);
  const pos = start + text.length;
  requestAnimationFrame(() => {
    target.focus({ preventScroll: true });
    target.setSelectionRange(pos, pos);
  });
}

// `targetRef` is the textarea/input to insert into, `value`/`onChange`
// are that same field's controlled state. `mode="text"` on the shared
// panel, since a pick here becomes part of running message content, not
// a single exact value.
export default function EmojiInsertButton({ targetRef, value, onChange, guildId }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function pick(emoji) {
    if (targetRef.current) insertAtCursor(targetRef.current, value, onChange, emoji);
    // Deferred rather than called synchronously here: removing the
    // clicked button's own DOM subtree (closing this panel) in direct
    // response to its own click, within the same event-handling tick,
    // triggers a real Chromium quirk -- the browser's focus manager, on
    // finding the active element gone, can synthesize a phantom
    // follow-up "click" (detail: 0) on whatever next receives focus
    // (observed: the first focusable button elsewhere on the page, e.g.
    // MarkdownToolbar's Heading button, silently corrupting unrelated
    // state). Closing on the next tick lets the browser finish its own
    // click bookkeeping first.
    setTimeout(() => setOpen(false), 0);
  }

  return (
    <div className="emoji-insert" ref={rootRef}>
      <button
        type="button"
        className="emoji-insert-trigger"
        title="Insert emoji"
        aria-label="Insert emoji"
        onClick={() => setOpen((v) => !v)}
      >
        <Smile size={14} />
      </button>
      {open && (
        <div className="emoji-insert-panel">
          <EmojiPickerPanel guildId={guildId} mode="text" onPick={pick} />
        </div>
      )}
    </div>
  );
}

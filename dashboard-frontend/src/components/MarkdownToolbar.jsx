import { Bold, Italic, Underline, Strikethrough, Code, EyeOff, Heading1, Heading2, List, ListOrdered, Quote } from "lucide-react";

// Wraps the current selection in `before`/`after` (or inserts `placeholder`
// between them if nothing's selected), then puts the cursor/selection back
// where you'd expect so you can keep typing without reaching for the mouse.
function wrapSelection(textarea, value, onChange, before, after, placeholder) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = value.slice(start, end) || placeholder;
  const next = value.slice(0, start) + before + selected + after + value.slice(end);
  onChange(next);
  const selStart = start + before.length;
  requestAnimationFrame(() => {
    textarea.focus({ preventScroll: true });
    textarea.setSelectionRange(selStart, selStart + selected.length);
  });
}

// Prefixes every line touched by the current selection with `prefix`
// (e.g. "# ", "- ", "> "), the way most markdown editors treat a
// line-level action: it applies to whichever line(s) your cursor/selection
// spans, not just the exact characters highlighted. Leaves the cursor
// collapsed at the end of the prefixed block, not a selection covering it:
// unlike wrapSelection's placeholder (meant to be typed over), there's
// nothing here worth replacing, and selecting it just means the prefix
// itself vanishes the moment you start typing.
function prefixLines(textarea, value, onChange, prefix) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  let lineEnd = value.indexOf("\n", end);
  if (lineEnd === -1) lineEnd = value.length;
  const block = value.slice(lineStart, lineEnd);
  const prefixed = block.split("\n").map((l) => prefix + l).join("\n");
  const next = value.slice(0, lineStart) + prefixed + value.slice(lineEnd);
  onChange(next);
  const cursorPos = lineStart + prefixed.length;
  requestAnimationFrame(() => {
    textarea.focus({ preventScroll: true });
    textarea.setSelectionRange(cursorPos, cursorPos);
  });
}

const BUTTONS = [
  { icon: Heading1, title: "Heading", action: (ta, v, oc) => prefixLines(ta, v, oc, "# ") },
  { icon: Heading2, title: "Subheading", action: (ta, v, oc) => prefixLines(ta, v, oc, "## ") },
  { icon: Bold, title: "Bold", action: (ta, v, oc) => wrapSelection(ta, v, oc, "**", "**", "bold text") },
  { icon: Italic, title: "Italic", action: (ta, v, oc) => wrapSelection(ta, v, oc, "*", "*", "italic text") },
  { icon: Underline, title: "Underline", action: (ta, v, oc) => wrapSelection(ta, v, oc, "__", "__", "underlined text") },
  { icon: Strikethrough, title: "Strikethrough", action: (ta, v, oc) => wrapSelection(ta, v, oc, "~~", "~~", "strikethrough text") },
  { icon: Code, title: "Code", action: (ta, v, oc) => wrapSelection(ta, v, oc, "`", "`", "code") },
  { icon: EyeOff, title: "Spoiler", action: (ta, v, oc) => wrapSelection(ta, v, oc, "||", "||", "spoiler") },
  { icon: List, title: "Bullet list", action: (ta, v, oc) => prefixLines(ta, v, oc, "- ") },
  { icon: ListOrdered, title: "Numbered list", action: (ta, v, oc) => prefixLines(ta, v, oc, "1. ") },
  { icon: Quote, title: "Quote", action: (ta, v, oc) => prefixLines(ta, v, oc, "> ") },
];

// Continues a bullet/numbered/quote line onto the next one when Enter is
// pressed partway through typing it, the way most markdown editors do,
// instead of making you retype "- " or "3. " yourself on every line.
// Pressing Enter on an already-empty list/quote line ends the list
// instead of adding another empty one, same as those editors too. Wire
// this to a textarea's onKeyDown alongside its usual onChange.
export function handleListContinue(e, value, onChange) {
  if (e.key !== "Enter" || e.shiftKey) return;
  const textarea = e.target;
  const pos = textarea.selectionStart;
  if (pos !== textarea.selectionEnd) return; // let a real selection just get replaced normally
  const lineStart = value.lastIndexOf("\n", pos - 1) + 1;
  const line = value.slice(lineStart, pos);

  let prefix = null;
  let rest = "";
  let m;
  if ((m = /^(\s*)([-*])\s(.*)$/.exec(line))) {
    prefix = `${m[1]}${m[2]} `;
    rest = m[3];
  } else if ((m = /^(\s*)(\d+)\.\s(.*)$/.exec(line))) {
    prefix = `${m[1]}${Number(m[2]) + 1}. `;
    rest = m[3];
  } else if ((m = /^(\s*)>\s(.*)$/.exec(line))) {
    prefix = `${m[1]}> `;
    rest = m[3];
  }
  if (prefix === null) return; // not on a list/quote line, let Enter behave normally

  e.preventDefault();
  if (!rest.trim()) {
    // Empty list item: pressing Enter again ends the list instead of
    // continuing it, by removing this line's prefix rather than adding one.
    const next = value.slice(0, lineStart) + value.slice(pos);
    onChange(next);
    requestAnimationFrame(() => {
      textarea.focus({ preventScroll: true });
      textarea.setSelectionRange(lineStart, lineStart);
    });
    return;
  }
  const insertion = "\n" + prefix;
  const next = value.slice(0, pos) + insertion + value.slice(pos);
  onChange(next);
  const newPos = pos + insertion.length;
  requestAnimationFrame(() => {
    textarea.focus({ preventScroll: true });
    textarea.setSelectionRange(newPos, newPos);
  });
}

export default function MarkdownToolbar({ textareaRef, value, onChange }) {
  return (
    <div className="markdown-toolbar" role="toolbar" aria-label="Text formatting">
      {BUTTONS.map(({ icon: Icon, title, action }) => (
        <button
          key={title}
          type="button"
          className="markdown-toolbar-btn"
          title={title}
          aria-label={title}
          onClick={() => {
            if (textareaRef.current) action(textareaRef.current, value, onChange);
          }}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  );
}

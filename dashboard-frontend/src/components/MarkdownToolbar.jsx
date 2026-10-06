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
    textarea.focus();
    textarea.setSelectionRange(selStart, selStart + selected.length);
  });
}

// Prefixes every line touched by the current selection with `prefix`
// (e.g. "# ", "- ", "> "), the way most markdown editors treat a
// line-level action: it applies to whichever line(s) your cursor/selection
// spans, not just the exact characters highlighted.
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
  requestAnimationFrame(() => {
    textarea.focus();
    textarea.setSelectionRange(lineStart, lineStart + prefixed.length);
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

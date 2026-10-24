import { useEffect, useRef, useState } from "react";
import { Palette, Check } from "lucide-react";

const STORAGE_KEY = "fluxbot-palette";
const CUSTOM_COLORS_KEY = "fluxbot-custom-colors";

// Independent of ThemeToggle's light/dark axis: this picks which color
// system is active (original FluxBot blue/purple, Badlands Red's sharp,
// squared look, or a user-picked custom accent), each of which still has
// its own light and dark variant. Two separate controls rather than one
// combined picker, same reasoning as keeping data-theme and data-palette
// as separate HTML attributes: a person who likes a custom accent in dark
// mode and Original in light mode (or any other combination) isn't forced
// to pick one axis just because it's bundled with the other.
const PALETTES = [
  { id: "original", label: "Original" },
  { id: "badlands-red", label: "Badlands Red" },
  { id: "custom", label: "Custom" },
];

// Original's own blue/purple, reused here as the starting point for a
// first-time custom palette so it doesn't open on some arbitrary color.
const DEFAULT_CUSTOM_COLORS = { accent: "#6d7bff", gradientEnd: "#a78bfa" };

function getInitialPalette() {
  const stored = localStorage.getItem(STORAGE_KEY);
  return PALETTES.some((p) => p.id === stored) ? stored : "original";
}

function getInitialCustomColors() {
  try {
    const stored = JSON.parse(localStorage.getItem(CUSTOM_COLORS_KEY));
    if (/^#[0-9a-f]{6}$/i.test(stored?.accent) && /^#[0-9a-f]{6}$/i.test(stored?.gradientEnd)) {
      return stored;
    }
  } catch {
    // missing/malformed storage; fall through to the default below
  }
  return DEFAULT_CUSTOM_COLORS;
}

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function toHex2(n) {
  return n.toString(16).padStart(2, "0");
}

// The user only picks one accent color, not every state it needs (hover,
// a soft background tint), so those two are derived from it rather than
// adding more color pickers for shades most people won't think to tweak.
function darken(hex, amount) {
  const { r, g, b } = hexToRgb(hex);
  const f = (c) => Math.max(0, Math.round(c * (1 - amount)));
  return `#${toHex2(f(r))}${toHex2(f(g))}${toHex2(f(b))}`;
}

function withAlpha(hex, alpha) {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function applyCustomColors(colors) {
  const root = document.documentElement.style;
  root.setProperty("--accent", colors.accent);
  root.setProperty("--accent-hover", darken(colors.accent, 0.12));
  root.setProperty("--accent-soft", withAlpha(colors.accent, 0.14));
  root.setProperty("--accent-gradient-end", colors.gradientEnd);
}

function clearCustomColors() {
  const root = document.documentElement.style;
  root.removeProperty("--accent");
  root.removeProperty("--accent-hover");
  root.removeProperty("--accent-soft");
  root.removeProperty("--accent-gradient-end");
}

export default function PalettePicker() {
  const [palette, setPalette] = useState(getInitialPalette);
  const [customColors, setCustomColors] = useState(getInitialCustomColors);
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-palette", palette);
    localStorage.setItem(STORAGE_KEY, palette);
    // Inline custom-property overrides outlive a palette switch (they're
    // set on the root element itself, not scoped to [data-palette=...]),
    // so Original/Badlands Red have to have them explicitly cleared or
    // they'd keep showing a stale custom accent instead of their own.
    if (palette === "custom") {
      applyCustomColors(customColors);
    } else {
      clearCustomColors();
    }
    // customColors is applied here too (for the initial switch into
    // "custom") and in the effect below (for edits after); re-running
    // this one on every keystroke would just redo the same work.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [palette]);

  useEffect(() => {
    localStorage.setItem(CUSTOM_COLORS_KEY, JSON.stringify(customColors));
    if (palette === "custom") applyCustomColors(customColors);
  }, [customColors, palette]);

  useEffect(() => {
    function onClickOutside(e) {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div className="palette-picker" ref={rootRef}>
      <button
        type="button"
        className="theme-toggle"
        onClick={() => setOpen((v) => !v)}
        title="Change color theme"
        aria-label="Change color theme"
        aria-expanded={open}
      >
        <Palette size={16} />
      </button>
      {open && (
        <div className="palette-picker-panel">
          {PALETTES.map((p) => (
            <button
              key={p.id}
              type="button"
              className="palette-picker-option"
              onClick={() => {
                setPalette(p.id);
                // Custom's panel stays open so the color pickers it reveals
                // below are immediately reachable, no second click needed.
                if (p.id !== "custom") setOpen(false);
              }}
            >
              <span
                className={p.id === "custom" ? "palette-swatch" : `palette-swatch palette-swatch-${p.id}`}
                style={p.id === "custom"
                  ? { background: `linear-gradient(135deg, ${customColors.accent}, ${customColors.gradientEnd})` }
                  : undefined}
              />
              {p.label}
              {palette === p.id && <Check size={14} className="palette-picker-check" />}
            </button>
          ))}
          {palette === "custom" && (
            <div className="palette-picker-custom">
              <label className="palette-picker-color-row">
                <span>Accent</span>
                <input
                  type="color"
                  value={customColors.accent}
                  onChange={(e) => setCustomColors((c) => ({ ...c, accent: e.target.value }))}
                  aria-label="Custom accent color"
                />
              </label>
              <label className="palette-picker-color-row">
                <span>Gradient</span>
                <input
                  type="color"
                  value={customColors.gradientEnd}
                  onChange={(e) => setCustomColors((c) => ({ ...c, gradientEnd: e.target.value }))}
                  aria-label="Custom gradient color"
                />
              </label>
              <button
                type="button"
                className="palette-picker-reset"
                onClick={() => setCustomColors(DEFAULT_CUSTOM_COLORS)}
              >
                Reset to default
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

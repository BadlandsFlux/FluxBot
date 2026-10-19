import { useEffect, useRef, useState } from "react";
import { Palette, Check } from "lucide-react";

const STORAGE_KEY = "fluxbot-palette";

// Independent of ThemeToggle's light/dark axis: this picks which color
// system is active (original FluxBot blue/purple, or Badlands Red's
// sharp, squared look), each of which still has its own light and dark
// variant. Two separate controls rather than one combined picker, same
// reasoning as keeping data-theme and data-palette as separate HTML
// attributes: a person who likes Badlands Red in dark mode and Original
// in light mode (or any other combination) isn't forced to pick one
// axis just because it's bundled with the other.
const PALETTES = [
  { id: "original", label: "Original" },
  { id: "badlands-red", label: "Badlands Red" },
];

function getInitialPalette() {
  const stored = localStorage.getItem(STORAGE_KEY);
  return PALETTES.some((p) => p.id === stored) ? stored : "original";
}

export default function PalettePicker() {
  const [palette, setPalette] = useState(getInitialPalette);
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-palette", palette);
    localStorage.setItem(STORAGE_KEY, palette);
  }, [palette]);

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
                setOpen(false);
              }}
            >
              <span className={`palette-swatch palette-swatch-${p.id}`} />
              {p.label}
              {palette === p.id && <Check size={14} className="palette-picker-check" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Switch({ checked, onChange, label }) {
  return (
    <div className="switch-row">
      {label && <span className="switch-label">{label}</span>}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        className={`switch ${checked ? "on" : ""}`}
        onClick={() => onChange(!checked)}
      >
        <span className="switch-thumb" />
      </button>
    </div>
  );
}

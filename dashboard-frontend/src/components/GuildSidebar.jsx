import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChevronsLeft, ChevronsRight } from "lucide-react";

const COLLAPSE_KEY = "fluxbot-sidebar-collapsed";

export default function GuildSidebar({ tabs, activeTab, onTabChange, counts }) {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === "1");
  const navRef = useRef(null);
  const itemRefs = useRef({});
  const [indicator, setIndicator] = useState(null); // {top, height}
  const prevCounts = useRef({});
  const [pulsing, setPulsing] = useState({});

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  // Slide the accent indicator to whichever item is active. Measured against
  // the nav container so it works the same whether the sidebar is a vertical
  // column (desktop) or a horizontal strip (the CSS-only mobile fallback),
  // no separate code path for either orientation.
  useLayoutEffect(() => {
    const el = itemRefs.current[activeTab];
    const nav = navRef.current;
    if (!el || !nav) return;
    const elRect = el.getBoundingClientRect();
    const navRect = nav.getBoundingClientRect();
    setIndicator({
      top: elRect.top - navRect.top + nav.scrollTop,
      height: elRect.height,
      left: elRect.left - navRect.left + nav.scrollLeft,
      width: elRect.width,
    });
    el.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeTab, collapsed, tabs]);

  // Brief pulse on a badge when its count changes, ties the sidebar into the
  // page's own quiet 8s live-poll instead of counts just silently changing.
  useEffect(() => {
    const next = {};
    let anyChanged = false;
    for (const t of tabs) {
      const c = counts[t.id];
      if (c != null && prevCounts.current[t.id] != null && c !== prevCounts.current[t.id]) {
        next[t.id] = true;
        anyChanged = true;
      }
      if (c != null) prevCounts.current[t.id] = c;
    }
    if (anyChanged) {
      setPulsing(next);
      const timer = setTimeout(() => setPulsing({}), 600);
      return () => clearTimeout(timer);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [counts]);

  const groups = [];
  for (const t of tabs) {
    const key = t.category || "__standalone__";
    let group = groups.find((g) => g.key === key);
    if (!group) {
      group = { key, label: t.category, items: [] };
      groups.push(group);
    }
    group.items.push(t);
  }

  return (
    <aside className={`guild-sidebar ${collapsed ? "collapsed" : ""}`}>
      <nav className="sidebar-nav" ref={navRef}>
        {indicator && <div className="sidebar-indicator" style={{
          "--indicator-top": `${indicator.top}px`,
          "--indicator-height": `${indicator.height}px`,
          "--indicator-left": `${indicator.left}px`,
          "--indicator-width": `${indicator.width}px`,
        }} />}
        {groups.map((group) => (
          <div className="sidebar-group" key={group.key}>
            {group.label && <div className="sidebar-group-label">{group.label}</div>}
            {group.items.map((t) => {
              const Icon = t.icon;
              const count = counts[t.id];
              const isActive = activeTab === t.id;
              return (
                <button
                  key={t.id}
                  ref={(el) => (itemRefs.current[t.id] = el)}
                  className={`sidebar-item ${isActive ? "active" : ""}`}
                  onClick={() => onTabChange(t.id)}
                  title={collapsed ? t.label : undefined}
                >
                  <Icon size={16} className="sidebar-item-icon" />
                  {!collapsed && <span className="sidebar-item-label">{t.label}</span>}
                  {!collapsed && count != null && (
                    <span className={`sidebar-item-count ${pulsing[t.id] ? "pulse" : ""}`}>{count}</span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </nav>
      <button
        type="button"
        className="sidebar-collapse-btn"
        onClick={() => setCollapsed((c) => !c)}
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {collapsed ? <ChevronsRight size={15} /> : <ChevronsLeft size={15} />}
        {!collapsed && <span>Collapse</span>}
      </button>
    </aside>
  );
}

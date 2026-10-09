import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Zap, Home, Menu, X } from "lucide-react";
import { api } from "../api";
import GuildSwitcher from "./GuildSwitcher";
import ThemeToggle from "./ThemeToggle";

export default function TopBar({ user, isOwner, botName, onLoggedOut }) {
  const [iconFailed, setIconFailed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const location = useLocation();
  // GuildSwitcher already hides itself off a guild page, but when it IS
  // showing, it's also the fastest way to jump to a different server
  // (search + one click, no detour through the picker page), so the
  // plain "Servers" link next to it would just be two ways to do the
  // same thing competing for the same cramped row.
  const onGuildPage = /^\/guild\//.test(location.pathname);

  useEffect(() => {
    function onClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  // Collapsing to a new page closes the dropdown too, same as it would
  // if this were two separate components instead of one that's just
  // visually repositioned by a breakpoint.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  async function handleLogout() {
    await api.logout();
    onLoggedOut();
  }

  // Rendered twice -- inline in .topbar-nav for desktop, and again
  // inside .topbar-menu-panel for the mobile dropdown -- rather than
  // one list repositioned by CSS, since the two need different
  // containers (an inline row vs. an absolutely-positioned panel) and
  // only one of the two is ever visible at a given width.
  const navLinks = (
    <>
      <Link to="/commands" className="topbar-link" onClick={() => setMenuOpen(false)}>
        Commands
      </Link>
      <Link to="/status" className="topbar-link" onClick={() => setMenuOpen(false)}>
        Status
      </Link>
      {isOwner && (
        <Link to="/bot-profile" className="topbar-link" onClick={() => setMenuOpen(false)}>
          Bot Profile
        </Link>
      )}
      {isOwner && (
        <Link to="/discord-relay-setup" className="topbar-link" onClick={() => setMenuOpen(false)}>
          Discord Relay
        </Link>
      )}
      {isOwner && (
        <Link to="/fluxer-status" className="topbar-link" onClick={() => setMenuOpen(false)}>
          Fluxer Status
        </Link>
      )}
    </>
  );

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link className="brand" to="/">
          <span className={`brand-mark${iconFailed ? "" : " brand-mark-custom"}`}>
            {iconFailed ? (
              <Zap size={16} strokeWidth={2.5} />
            ) : (
              <img src="/api/bot-profile/icon" alt="" onError={() => setIconFailed(true)} />
            )}
          </span>
          <span className="brand-text">{botName}</span>
        </Link>
        {user && !onGuildPage && (
          <Link to="/" className="topbar-home-btn" title="All servers">
            <Home size={15} />
            <span>Servers</span>
          </Link>
        )}
        {user && <GuildSwitcher />}
        <nav className="topbar-nav">{navLinks}</nav>
      </div>
      <div className="topbar-right">
        <ThemeToggle />
        {user && (
          <div className="topbar-user">
            <span className="user-pill">{user.username}</span>
            <button className="btn btn-ghost btn-small" onClick={handleLogout}>
              Log out
            </button>
          </div>
        )}
        <div className="topbar-menu" ref={menuRef}>
          <button
            type="button"
            className="topbar-menu-trigger"
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
          >
            {menuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          {menuOpen && (
            <div className="topbar-menu-panel">
              {navLinks}
              {user && (
                <>
                  <div className="topbar-menu-divider" />
                  <div className="topbar-menu-user">
                    <span className="user-pill">{user.username}</span>
                    <button className="btn btn-ghost btn-small" onClick={handleLogout}>
                      Log out
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

import { useState } from "react";
import { Link } from "react-router-dom";
import { Zap } from "lucide-react";
import { api } from "../api";
import GuildSwitcher from "./GuildSwitcher";
import ThemeToggle from "./ThemeToggle";

export default function TopBar({ user, isOwner, botName, onLoggedOut }) {
  const [iconFailed, setIconFailed] = useState(false);

  async function handleLogout() {
    await api.logout();
    onLoggedOut();
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link className="brand" to="/">
          <span className="brand-mark">
            {iconFailed ? (
              <Zap size={16} strokeWidth={2.5} />
            ) : (
              <img src="/api/bot-profile/icon" alt="" onError={() => setIconFailed(true)} />
            )}
          </span>
          <span className="brand-text">{botName}</span>
        </Link>
        {user && <GuildSwitcher />}
        <nav className="topbar-nav">
          <Link to="/commands" className="topbar-link">
            Commands
          </Link>
          <Link to="/status" className="topbar-link">
            Status
          </Link>
          {isOwner && (
            <Link to="/bot-profile" className="topbar-link">
              Bot Profile
            </Link>
          )}
          {isOwner && (
            <Link to="/discord-relay-setup" className="topbar-link">
              Discord Relay
            </Link>
          )}
        </nav>
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
      </div>
    </header>
  );
}

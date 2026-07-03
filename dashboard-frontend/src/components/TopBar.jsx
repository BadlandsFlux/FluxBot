import { Link } from "react-router-dom";
import { Zap } from "lucide-react";
import { api } from "../api";
import GuildSwitcher from "./GuildSwitcher";

export default function TopBar({ user, botName, onLoggedOut }) {
  async function handleLogout() {
    await api.logout();
    onLoggedOut();
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Link className="brand" to="/">
          <span className="brand-mark">
            <Zap size={16} strokeWidth={2.5} />
          </span>
          <span className="brand-text">{botName}</span>
        </Link>
        {user && <GuildSwitcher />}
        <nav className="topbar-nav">
          <Link to="/commands" className="topbar-link">
            Commands
          </Link>
        </nav>
      </div>
      {user && (
        <div className="topbar-user">
          <span className="user-pill">{user.username}</span>
          <button className="btn btn-ghost btn-small" onClick={handleLogout}>
            Log out
          </button>
        </div>
      )}
    </header>
  );
}

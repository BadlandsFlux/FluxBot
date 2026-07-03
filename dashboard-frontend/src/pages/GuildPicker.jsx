import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import Spinner from "../components/Spinner";

export default function GuildPicker() {
  const [guilds, setGuilds] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .guilds()
      .then((d) => setGuilds(d.guilds))
      .catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="card empty-state">
        <p className="error">{error}</p>
      </div>
    );
  }

  if (guilds === null) {
    return (
      <div className="loading-row">
        <Spinner />
        <span className="muted">Loading your servers…</span>
      </div>
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>Your servers</h1>
        <p className="muted">Servers where you can manage the bot.</p>
      </div>
      {guilds.length ? (
        <div className="grid">
          {guilds.map((g) => (
            <Link className="card guild-card" to={`/guild/${g.id}`} key={g.id}>
              {g.icon_url ? (
                <img className="guild-avatar-img" src={g.icon_url} alt="" />
              ) : (
                <div className="guild-avatar">{g.name ? g.name[0].toUpperCase() : "?"}</div>
              )}
              <div>
                <div className="guild-name">{g.name}</div>
                <div className="muted small">Manage settings →</div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card empty-state">
          <p>No manageable servers found.</p>
          <p className="muted small">
            Either the bot isn't in any of your servers yet, or you don't have "Manage Server"
            permissions there.
          </p>
        </div>
      )}
    </>
  );
}

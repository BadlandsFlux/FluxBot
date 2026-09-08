import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../api";

const GuildsContext = createContext({ guilds: [], loading: true, error: null, refresh: () => {} });

export function GuildsProvider({ enabled, children }) {
  const [guilds, setGuilds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    if (!enabled) {
      setGuilds([]);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .guilds()
      .then((d) => {
        setGuilds(d.guilds);
        setError(null);
      })
      .catch((err) => {
        // A 401 here also triggers the app-wide unauthorized handler
        // (api.js), which resets the whole app to its logged-out
        // state, so this error message won't actually be shown for
        // that case, the login page takes over instead. This still
        // covers a genuine transient failure (Fluxer briefly down,
        // etc.), where "no manageable servers" would otherwise be
        // shown, indistinguishable from actually having none.
        setError(err.status === 401 ? null : "Couldn't load your servers, try refreshing.");
      })
      .finally(() => setLoading(false));
  }, [enabled]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return <GuildsContext.Provider value={{ guilds, loading, error, refresh }}>{children}</GuildsContext.Provider>;
}

export function useGuilds() {
  return useContext(GuildsContext);
}

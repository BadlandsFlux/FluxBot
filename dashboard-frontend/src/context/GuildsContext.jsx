import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "../api";

const GuildsContext = createContext({ guilds: [], loading: true, refresh: () => {} });

export function GuildsProvider({ enabled, children }) {
  const [guilds, setGuilds] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    if (!enabled) {
      setGuilds([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    api
      .guilds()
      .then((d) => setGuilds(d.guilds))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [enabled]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return <GuildsContext.Provider value={{ guilds, loading, refresh }}>{children}</GuildsContext.Provider>;
}

export function useGuilds() {
  return useContext(GuildsContext);
}

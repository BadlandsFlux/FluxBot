import { useEffect, useState } from "react";
import { api } from "../api";

export default function useRolesChannels(guildId) {
  const [roles, setRoles] = useState([]);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([api.roles(guildId), api.channels(guildId)])
      .then(([r, c]) => {
        if (cancelled) return;
        setRoles(r.roles);
        setChannels(c.channels);
        setError(null);
      })
      .catch((e) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [guildId]);

  return { roles, channels, loading, error };
}

import { useEffect, useState } from "react";
import { api } from "../api";

// Shared by EmojiPicker (to resolve a picked custom-emoji value back to a
// friendly thumbnail+name for its trigger) and EmojiPickerPanel (to list
// them for picking), so opening/closing a picker repeatedly doesn't
// re-fetch the same guild's emoji list from scratch each time.
export default function useGuildEmojis(guildId) {
  const [emojis, setEmojis] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!guildId) {
      setEmojis([]);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    api
      .guildEmojis(guildId)
      .then((data) => {
        if (!cancelled) setEmojis(data.emojis || []);
      })
      .catch(() => {
        // Best-effort: callers still work with an empty list (e.g. the
        // standard emoji grid in EmojiPickerPanel doesn't depend on this).
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [guildId]);

  return { emojis, loading };
}

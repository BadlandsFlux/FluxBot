import { useEffect, useRef } from "react";

/**
 * Calls `callback` every `delayMs` while the document is visible. Pauses
 * automatically when the tab is backgrounded (visibilitychange) so we're
 * not polling an API the user isn't even looking at.
 */
export default function usePolling(callback, delayMs, enabled = true) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled || !delayMs) return;

    let intervalId = null;

    function start() {
      if (intervalId) return;
      intervalId = setInterval(() => callbackRef.current(), delayMs);
    }
    function stop() {
      if (intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }
    function onVisibilityChange() {
      if (document.visibilityState === "visible") start();
      else stop();
    }

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibilityChange);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [delayMs, enabled]);
}

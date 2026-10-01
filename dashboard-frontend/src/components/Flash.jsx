import { createContext, useCallback, useContext, useRef, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

const FlashContext = createContext(() => {});

// Caps how many toasts can be on screen at once. A burst of events (several
// reports/replies landing close together, say) shouldn't be able to bury
// the whole page in stacked 4s toasts.
const MAX_VISIBLE = 4;
const DISMISS_MS = 4000;

export function FlashProvider({ children }) {
  const [items, setItems] = useState([]);
  const idRef = useRef(0);
  const timersRef = useRef(new Map()); // id -> timeout handle

  const dismiss = useCallback((id) => {
    clearTimeout(timersRef.current.get(id));
    timersRef.current.delete(id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  }, []);

  const push = useCallback(
    (message, kind = "success") => {
      setItems((prev) => {
        // The same message already showing (e.g. a rapid double-fire of
        // the same event) just restarts its own timer instead of
        // stacking a second identical toast on top of it.
        const existing = prev.find((i) => i.message === message && i.kind === kind);
        if (existing) {
          clearTimeout(timersRef.current.get(existing.id));
          timersRef.current.set(existing.id, setTimeout(() => dismiss(existing.id), DISMISS_MS));
          return prev;
        }

        const id = ++idRef.current;
        timersRef.current.set(id, setTimeout(() => dismiss(id), DISMISS_MS));
        let next = [...prev, { id, message, kind }];
        if (next.length > MAX_VISIBLE) {
          const [oldest, ...rest] = next;
          clearTimeout(timersRef.current.get(oldest.id));
          timersRef.current.delete(oldest.id);
          next = rest;
        }
        return next;
      });
    },
    [dismiss]
  );

  return (
    <FlashContext.Provider value={push}>
      {children}
      {/* role="status" + aria-live announces each toast to screen readers,
          which otherwise get no indication at all that an action (kick,
          save, etc.) succeeded or failed beyond this visual-only stack.
          "polite" so it queues behind whatever the user's already
          listening to rather than interrupting mid-sentence. */}
      <div className="flash-stack" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`flash flash-${item.kind}`}>
            {item.kind === "error" ? <XCircle size={16} /> : <CheckCircle2 size={16} />}
            <span>{item.message}</span>
          </div>
        ))}
      </div>
    </FlashContext.Provider>
  );
}

export function useFlash() {
  return useContext(FlashContext);
}

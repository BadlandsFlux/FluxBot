import { createContext, useCallback, useContext, useRef, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";

const FlashContext = createContext(() => {});

export function FlashProvider({ children }) {
  const [items, setItems] = useState([]);
  const idRef = useRef(0);

  const push = useCallback((message, kind = "success") => {
    const id = ++idRef.current;
    setItems((prev) => [...prev, { id, message, kind }]);
    setTimeout(() => {
      setItems((prev) => prev.filter((i) => i.id !== id));
    }, 4000);
  }, []);

  return (
    <FlashContext.Provider value={push}>
      {children}
      <div className="flash-stack">
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

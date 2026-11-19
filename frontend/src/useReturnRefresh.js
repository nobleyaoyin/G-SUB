import { useEffect, useRef } from "react";

// Revalidate after returning to the tab; never issue a mutation from this hook.
export default function useReturnRefresh(callback, busy = false) {
  const latest = useRef({ callback, busy });
  useEffect(() => { latest.current = { callback, busy }; }, [callback, busy]);
  useEffect(() => {
    const onFocus = () => {
      if (!latest.current.busy && document.visibilityState === "visible") {
        Promise.resolve().then(() => latest.current.callback()).catch(() => {});
      }
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);
}

import { RefObject, useEffect } from "react";

export function useAutoScroll<T extends HTMLElement>(
  elRef: RefObject<T | null>,
  stickToBottomRef: RefObject<boolean>,
  deps: any[]
) {
  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    if (!stickToBottomRef.current) return;
    try {
      el.scrollTop = el.scrollHeight;
    } catch {
      // ignore
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

import { useEffect } from "react";

export function useFullscreenEscape(leftFullscreen: boolean, setLeftFullscreen: (v: boolean) => void) {
  useEffect(() => {
    if (!leftFullscreen) return;

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLeftFullscreen(false);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [leftFullscreen, setLeftFullscreen]);
}

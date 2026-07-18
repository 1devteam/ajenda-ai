import { useEffect, useState } from "react";

export type AccessibilityPreferences = {
  reducedMotion: boolean;
};

export function useAccessibilityPreferences(): AccessibilityPreferences {
  const [reducedMotion, setReducedMotion] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );

  useEffect(() => {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    function sync() {
      setReducedMotion(motionQuery.matches);
    }
    sync();
    motionQuery.addEventListener("change", sync);
    return () => motionQuery.removeEventListener("change", sync);
  }, []);

  return { reducedMotion };
}

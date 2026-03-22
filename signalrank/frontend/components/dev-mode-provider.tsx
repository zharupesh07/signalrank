"use client";

import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from "react";

interface DevModeContextValue {
  isDevMode: boolean;
  isDevPanelOpen: boolean;
  openDevPanel: () => void;
  closeDevPanel: () => void;
  handleLogoClick: () => void;
}

const DevModeContext = createContext<DevModeContextValue>({
  isDevMode: false,
  isDevPanelOpen: false,
  openDevPanel: () => {},
  closeDevPanel: () => {},
  handleLogoClick: () => {},
});

export function useDevMode() {
  return useContext(DevModeContext);
}

const CLICK_THRESHOLD = 5;
const CLICK_WINDOW_MS = 2000;
const STORAGE_KEY = "signalrank-dev-mode";

export function DevModeProvider({ children }: { children: ReactNode }) {
  const [isDevMode, setIsDevMode] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(STORAGE_KEY) === "true";
  });
  const [isDevPanelOpen, setIsDevPanelOpen] = useState(false);
  const clickTimestamps = useRef<number[]>([]);

  const handleLogoClick = useCallback(() => {
    const now = Date.now();
    clickTimestamps.current = clickTimestamps.current.filter(
      (t) => now - t < CLICK_WINDOW_MS
    );
    clickTimestamps.current.push(now);

    if (clickTimestamps.current.length >= CLICK_THRESHOLD) {
      clickTimestamps.current = [];
      const next = !isDevMode;
      setIsDevMode(next);
      localStorage.setItem(STORAGE_KEY, String(next));
      if (!next) setIsDevPanelOpen(false);
    }
  }, [isDevMode]);

  const openDevPanel = useCallback(() => setIsDevPanelOpen(true), []);
  const closeDevPanel = useCallback(() => setIsDevPanelOpen(false), []);

  return (
    <DevModeContext.Provider value={{ isDevMode, isDevPanelOpen, openDevPanel, closeDevPanel, handleLogoClick }}>
      {children}
    </DevModeContext.Provider>
  );
}

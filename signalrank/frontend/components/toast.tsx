"use client";

import { createContext, useCallback, useContext, useRef, useState } from "react";
import { X } from "lucide-react";

type ToastType = "success" | "error" | "info";

interface Toast {
  id: string;
  message: string;
  type: ToastType;
  exiting?: boolean;
}

interface ToastContextValue {
  toast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue>({ toast: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

const BORDER_COLOR: Record<ToastType, string> = {
  success: "border-l-[#22c55e]",
  error: "border-l-[#ef4444]",
  info: "border-l-[#52525b]",
};

const DOT_COLOR: Record<ToastType, string> = {
  success: "bg-[#22c55e]",
  error: "bg-[#ef4444]",
  info: "bg-[#71717a]",
};

const PREFIX: Record<ToastType, string> = {
  success: "> OK",
  error: "> ERR",
  info: "> INFO",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 260);
  }, []);

  const toast = useCallback(
    (message: string, type: ToastType = "info") => {
      const id = Math.random().toString(36).slice(2);
      setToasts((prev) => [...prev, { id, message, type }]);
      const timer = setTimeout(() => dismiss(id), 4000);
      timers.current.set(id, timer);
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed top-14 right-4 z-[100] flex flex-col gap-2 max-w-[340px]">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`
              flex items-start gap-3 bg-[#18181b] border border-[#3f3f46] border-l-2
              ${BORDER_COLOR[t.type]}
              px-3 py-2.5 text-xs font-mono
              ${t.exiting ? "toast-exit" : "toast-enter"}
            `}
          >
            <div className={`w-1.5 h-1.5 rounded-full mt-0.5 shrink-0 ${DOT_COLOR[t.type]}`} />
            <div className="flex-1 min-w-0">
              <span className="text-[#52525b] mr-1.5">{PREFIX[t.type]}</span>
              <span className="text-[#a1a1aa] break-words">{t.message}</span>
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="text-[#52525b] hover:text-[#a1a1aa] shrink-0"
            >
              <X size={10} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

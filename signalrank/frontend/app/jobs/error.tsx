"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-4xl mx-auto px-6 py-8 flex items-center justify-center min-h-[50vh]">
        <div className="font-mono text-xs space-y-4 text-center">
          <div className="text-red-500 tracking-wider">
            <span className="text-muted-foreground">&gt; </span>ERR Something went wrong
          </div>
          {error.message && (
            <div className="text-muted-foreground max-w-md truncate">{error.message}</div>
          )}
          <button
            onClick={reset}
            className="px-4 py-2 border border-primary text-primary hover:bg-primary hover:text-primary-foreground transition-colors text-xs tracking-wider uppercase"
          >
            Retry
          </button>
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { useToast } from "@/components/toast";
import { X, Loader2 } from "lucide-react";

type ExtractedJob = {
  title: string;
  company: string;
  location: string;
  job_url: string;
  date_posted: string | null;
  description: string;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
};

type Step = "paste" | "validate" | "manual";

export default function AddJobModal({ open, onClose, onAdded }: Props) {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast: showToast } = useToast();

  const [step, setStep] = useState<Step>("paste");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<{ message: string; retryable: boolean } | null>(null);
  const [extracted, setExtracted] = useState<ExtractedJob>({
    title: "", company: "", location: "", job_url: "", date_posted: null, description: "",
  });

  if (!open) return null;

  function reset() {
    setStep("paste");
    setInput("");
    setFetchError(null);
    setLoading(false);
    setExtracted({ title: "", company: "", location: "", job_url: "", date_posted: null, description: "" });
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function handleExtract(overrideText?: string) {
    const value = (overrideText ?? input).trim();
    if (!value) return;
    setLoading(true);
    setFetchError(null);

    const isUrl = value.startsWith("http://") || value.startsWith("https://");
    try {
      const result = await api.ingest.extract(token, isUrl ? { url: value } : { text: value });
      setExtracted(result);
      setStep("validate");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      let detail: { error?: string; retryable?: boolean; message?: string } = {};
      try {
        const jsonStr = msg.replace(/^\d+: /, "");
        detail = JSON.parse(jsonStr);
      } catch { /* not JSON */ }

      if (detail.error === "fetch_failed") {
        setFetchError({ message: detail.message ?? "Couldn't fetch that URL.", retryable: detail.retryable ?? false });
      } else if (detail.error === "parse_failed") {
        setStep("manual");
      } else {
        showToast("Extraction failed — try pasting the JD text instead", "error");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    setLoading(true);
    try {
      const result = await api.ingest.confirm(token, extracted);
      if ("error" in result && result.error === "duplicate") {
        showToast("Already in your tracker", "info");
        handleClose();
        return;
      }
      const r = result as { priority: string };
      showToast(`Added as ${r.priority} — resume & email generating`, "success");
      handleClose();
      onAdded();
    } catch {
      showToast("Failed to save — please try again", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg mx-4 bg-card border border-border rounded-lg shadow-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Add Job</h2>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground">
            <X size={18} />
          </button>
        </div>

        {step === "paste" && (
          <div className="space-y-4">
            <textarea
              className="w-full h-32 p-3 text-sm bg-input border border-border rounded resize-none focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Paste a job URL or the full job description…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              autoFocus
            />
            {fetchError && (
              <div className="space-y-2">
                <p className="text-sm text-destructive">
                  Couldn&apos;t fetch that URL — paste the job description below instead.
                </p>
                {fetchError.retryable && (
                  <button
                    className="text-primary underline text-xs"
                    onClick={() => handleExtract(input)}
                  >
                    Try again
                  </button>
                )}
                <textarea
                  className="w-full h-32 p-3 text-sm bg-input border border-border rounded resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                  placeholder="Paste the job description here…"
                  onChange={(e) => setInput(e.target.value)}
                />
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={handleClose} className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground">
                Cancel
              </button>
              <button
                onClick={() => handleExtract()}
                disabled={!input.trim() || loading}
                className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
              >
                {loading && <Loader2 size={14} className="animate-spin" />}
                {loading ? "Extracting…" : "Extract"}
              </button>
            </div>
          </div>
        )}

        {(step === "validate" || step === "manual") && (
          <div className="space-y-3">
            {step === "manual" && (
              <p className="text-sm text-muted-foreground">
                Couldn&apos;t parse automatically — fill in the details below.
              </p>
            )}
            {(["title", "company", "location", "job_url"] as const).map((field) => (
              <div key={field}>
                <label className="block text-xs text-muted-foreground mb-1 capitalize">
                  {field.replace("_", " ")}
                </label>
                <input
                  className="w-full p-2 text-sm bg-input border border-border rounded focus:outline-none focus:ring-1 focus:ring-primary"
                  value={extracted[field]}
                  onChange={(e) => setExtracted((prev) => ({ ...prev, [field]: e.target.value }))}
                />
              </div>
            ))}
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Description</label>
              <textarea
                className="w-full h-24 p-2 text-sm bg-input border border-border rounded resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                value={extracted.description}
                onChange={(e) => setExtracted((prev) => ({ ...prev, description: e.target.value }))}
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={handleClose} className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground">
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={!extracted.title || !extracted.company || loading}
                className="px-4 py-2 text-sm bg-primary text-primary-foreground rounded hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
              >
                {loading && <Loader2 size={14} className="animate-spin" />}
                Add to Tracker
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

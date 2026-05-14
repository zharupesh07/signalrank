"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  KeyRound,
  Loader2,
  Play,
  Upload,
} from "lucide-react";
import { api } from "@/lib/api";

type DesktopStatus = Awaited<ReturnType<typeof api.desktop.status>>;
type ParsedPrefill = Awaited<ReturnType<typeof api.onboarding.parsed>>["prefill"];

const PROVIDERS = [
  {
    id: "openrouter",
    name: "OpenRouter",
    placeholder: "sk-or-v1-...",
    note: "Recommended",
  },
  {
    id: "openai",
    name: "OpenAI",
    placeholder: "sk-...",
    note: "Direct",
  },
  {
    id: "anthropic",
    name: "Anthropic",
    placeholder: "sk-ant-...",
    note: "Claude",
  },
];

function providerName(id: string) {
  return PROVIDERS.find((provider) => provider.id === id)?.name ?? id;
}

export default function DesktopSetupPage() {
  const router = useRouter();
  const [status, setStatus] = useState<DesktopStatus | null>(null);
  const [token, setToken] = useState("");
  const [provider, setProvider] = useState("openrouter");
  const [key, setKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [startingRun, setStartingRun] = useState(false);
  const [showProviderForm, setShowProviderForm] = useState(false);
  const [prefill, setPrefill] = useState<ParsedPrefill | null>(null);
  const [error, setError] = useState("");

  const selectedProviderConfigured = useMemo(
    () => Boolean(status?.providers?.find((item) => item.id === provider)?.configured),
    [provider, status]
  );

  const activeStep = useMemo(() => {
    if (showProviderForm) return 0;
    if (!status?.provider_configured) return 0;
    if (!status.resume_uploaded || !status.onboarding_complete) return 1;
    return 2;
  }, [showProviderForm, status]);

  const refreshStatus = useCallback(async () => {
    const next = await api.desktop.status();
    setStatus(next);
    setProvider(next.active_provider || next.provider || "openrouter");
    return next;
  }, []);

  const startSession = useCallback(async () => {
    const session = await api.desktop.session();
    const res = await signIn("credentials", {
      desktopToken: session.access_token,
      redirect: false,
    });
    if (res?.error) throw new Error("Could not start local session");
    setToken(session.access_token);
    return session.access_token;
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const next = await refreshStatus();
        if (cancelled) return;
        if (next.provider_configured) {
          const nextToken = await startSession();
          if (next.resume_uploaded && !next.onboarding_complete) {
            const parsed = await api.onboarding.parsed(nextToken);
            if (!cancelled) setPrefill(parsed.prefill);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Desktop backend is not ready");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    boot();
    return () => {
      cancelled = true;
    };
  }, [refreshStatus, startSession]);

  async function handleProviderSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.desktop.saveProviderKey(key, provider);
      await startSession();
      await refreshStatus();
      setKey("");
      setShowProviderForm(false);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : `${providerName(provider)} key could not be saved`
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleResumeUpload(file: File) {
    const activeToken = token || (await startSession());
    setUploading(true);
    setError("");
    try {
      await api.onboarding.uploadResume(activeToken, file);
      const parsed = await api.onboarding.parsed(activeToken);
      setPrefill(parsed.prefill);
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resume upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleStartScan() {
    const activeToken = token || (await startSession());
    setStartingRun(true);
    setError("");
    try {
      await api.runs.trigger(activeToken, "quick");
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start scan");
    } finally {
      setStartingRun(false);
    }
  }

  async function handleProviderAction(providerId: string, configured: boolean) {
    setProvider(providerId);
    setError("");
    if (!configured) {
      setShowProviderForm(true);
      return;
    }
    try {
      await api.desktop.setProviderPreference(providerId);
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not switch provider");
    }
  }

  return (
    <main className="min-h-screen bg-[#080808] px-4 pb-8 pt-24 text-[#e4e4e7]">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        <header className="flex flex-col gap-3 border-b border-[#2a2a2e] pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-2xl font-bold tracking-widest text-[#22c55e]">
              SIGNAL<span className="text-[#a3e635]">RANK</span>
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-widest text-[#71717a]">
              Local desktop setup
            </div>
          </div>
          {status?.provider_configured && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setShowProviderForm((current) => !current)}
                className="border border-[#2a2a2e] px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-[#a1a1aa] transition-colors hover:border-[#22c55e] hover:text-[#22c55e]"
              >
                Providers
              </button>
              <button
                type="button"
                onClick={() =>
                  router.replace(status.onboarding_complete ? "/dashboard" : "/onboarding")
                }
                className="border border-[#2a2a2e] px-3 py-2 text-[10px] font-bold uppercase tracking-widest text-[#a1a1aa] transition-colors hover:border-[#22c55e] hover:text-[#22c55e]"
              >
                {status.onboarding_complete ? "Dashboard" : "Profile review"}
              </button>
            </div>
          )}
        </header>

        <div className="grid gap-3 sm:grid-cols-3">
          {["Provider", "Resume", "First scan"].map((label, index) => (
            <div
              key={label}
              className={`border px-4 py-3 ${
                activeStep === index
                  ? "border-[#22c55e] bg-[#22c55e]/5"
                  : activeStep > index
                    ? "border-[#2a2a2e] bg-[#111113]"
                    : "border-[#1c1c1f] bg-[#0b0b0c]"
              }`}
            >
              <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest">
                {activeStep > index ? (
                  <CheckCircle2 size={14} className="text-[#22c55e]" />
                ) : (
                  <span className="text-[#71717a]">0{index + 1}</span>
                )}
                <span>{label}</span>
              </div>
            </div>
          ))}
        </div>

        {loading ? (
          <section className="border border-[#2a2a2e] bg-[#111113] p-6">
            <div className="flex items-center gap-2 text-sm text-[#a1a1aa]">
              <Loader2 size={16} className="animate-spin text-[#22c55e]" />
              Checking local setup...
            </div>
          </section>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
            <section className="border border-[#2a2a2e] bg-[#111113] p-5">
              {activeStep === 0 && (
                <form onSubmit={handleProviderSubmit} className="space-y-5">
                  <div className="grid gap-3 sm:grid-cols-3">
                    {PROVIDERS.map((item) => {
                      const configured = status?.providers?.find((p) => p.id === item.id)
                        ?.configured;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => setProvider(item.id)}
                          className={`border p-4 text-left transition-colors ${
                            provider === item.id
                              ? "border-[#22c55e] bg-[#22c55e]/5"
                              : "border-[#2a2a2e] hover:border-[#3f3f46]"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-sm font-semibold">{item.name}</span>
                            {configured && <CheckCircle2 size={14} className="text-[#22c55e]" />}
                          </div>
                          <div className="mt-2 text-[10px] uppercase tracking-wider text-[#71717a]">
                            {item.note}
                          </div>
                        </button>
                      );
                    })}
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-[10px] uppercase tracking-wider text-[#71717a]">
                      {providerName(provider)} API key
                    </label>
                    <div className="flex items-center border border-[#2a2a2e] bg-[#080808] transition-colors focus-within:border-[#22c55e]">
                      <KeyRound size={14} className="ml-3 text-[#22c55e]" />
                      <input
                        type="password"
                        value={key}
                        onChange={(e) => setKey(e.target.value)}
                        required
                        className="min-w-0 flex-1 bg-transparent px-3 py-3 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                        placeholder={
                          PROVIDERS.find((item) => item.id === provider)?.placeholder
                        }
                      />
                    </div>
                  </div>

                  <button
                    type="submit"
                    disabled={saving}
                    className="w-full bg-[#22c55e] py-3 text-xs font-bold uppercase tracking-widest text-[#0a0a0a] transition-colors hover:bg-[#a3e635] disabled:opacity-50"
                  >
                    {saving
                      ? "Validating..."
                      : selectedProviderConfigured
                        ? "Update key"
                        : "Save key"}
                  </button>
                </form>
              )}

              {activeStep === 1 && (
                <div className="space-y-5">
                  <label className="flex cursor-pointer flex-col items-center justify-center border border-dashed border-[#3f3f46] bg-[#080808] px-5 py-12 text-center transition-colors hover:border-[#22c55e]">
                    {uploading ? (
                      <Loader2 size={24} className="animate-spin text-[#22c55e]" />
                    ) : (
                      <Upload size={24} className="text-[#22c55e]" />
                    )}
                    <span className="mt-3 text-sm font-semibold">
                      {uploading ? "Parsing resume..." : "Upload resume"}
                    </span>
                    <span className="mt-1 text-xs text-[#71717a]">PDF, DOCX, or text</span>
                    <input
                      type="file"
                      className="hidden"
                      accept=".pdf,.doc,.docx,.txt"
                      disabled={uploading}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void handleResumeUpload(file);
                      }}
                    />
                  </label>

                  {prefill && (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <PrefillBlock label="Roles" values={prefill.target_roles} />
                      <PrefillBlock label="Locations" values={prefill.preferred_locations} />
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={() => router.replace("/onboarding")}
                    className="w-full border border-[#22c55e] py-3 text-xs font-bold uppercase tracking-widest text-[#22c55e] transition-colors hover:bg-[#22c55e] hover:text-[#080808]"
                  >
                    Review profile
                  </button>
                </div>
              )}

              {activeStep === 2 && (
                <div className="space-y-5">
                  <div className="border border-[#2a2a2e] bg-[#080808] p-5">
                    <div className="flex items-center gap-2 text-sm font-semibold">
                      <CheckCircle2 size={16} className="text-[#22c55e]" />
                      Ready for first scan
                    </div>
                    <div className="mt-3 grid gap-3 sm:grid-cols-3">
                      {["Scrape", "Embed", "Rank"].map((item) => (
                        <div key={item} className="border border-[#1c1c1f] px-3 py-2 text-xs">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={startingRun}
                    onClick={handleStartScan}
                    className="flex w-full items-center justify-center gap-2 bg-[#22c55e] py-3 text-xs font-bold uppercase tracking-widest text-[#0a0a0a] transition-colors hover:bg-[#a3e635] disabled:opacity-50"
                  >
                    {startingRun ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    Start scan
                  </button>
                </div>
              )}
            </section>

            <aside className="space-y-4">
              <section className="border border-[#2a2a2e] bg-[#111113] p-5">
                <div className="text-[10px] uppercase tracking-widest text-[#71717a]">
                  Provider health
                </div>
                <div className="mt-4 space-y-3">
                  {(status?.providers ?? []).map((item) => (
                    <div key={item.id} className="flex items-center justify-between gap-3 text-sm">
                      <div>
                        <div>{item.name}</div>
                        <div
                          className={`mt-0.5 text-[10px] uppercase tracking-wider ${
                            item.configured ? "text-[#22c55e]" : "text-[#71717a]"
                          }`}
                        >
                          {item.configured ? (item.active ? "Active" : "Ready") : "Needs key"}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleProviderAction(item.id, item.configured)}
                        className="shrink-0 border border-[#2a2a2e] px-2 py-1.5 text-[10px] font-bold uppercase tracking-wider text-[#a1a1aa] transition-colors hover:border-[#22c55e] hover:text-[#22c55e]"
                      >
                        {item.configured ? (item.active ? "Update" : "Use") : "Add"}
                      </button>
                    </div>
                  ))}
                </div>
              </section>

              {error && (
                <section className="flex gap-2 border border-[#ef4444]/40 bg-[#ef4444]/5 p-4 text-xs text-[#fca5a5]">
                  <AlertCircle size={15} className="mt-0.5 shrink-0" />
                  <span>{error}</span>
                </section>
              )}

              <section className="border border-[#2a2a2e] bg-[#111113] p-5 text-xs text-[#a1a1aa]">
                <div className="text-[10px] uppercase tracking-widest text-[#71717a]">
                  Local state
                </div>
                <div className="mt-4 space-y-2">
                  <StatusRow label="Provider" value={status?.provider ?? "Not set"} />
                  <StatusRow
                    label="Resume"
                    value={status?.resume_uploaded ? "Uploaded" : "Missing"}
                  />
                  <StatusRow
                    label="Profile"
                    value={status?.onboarding_complete ? "Complete" : "Review needed"}
                  />
                </div>
              </section>
            </aside>
          </div>
        )}
      </div>
    </main>
  );
}

function PrefillBlock({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="border border-[#2a2a2e] bg-[#080808] p-3">
      <div className="text-[10px] uppercase tracking-wider text-[#71717a]">{label}</div>
      <div className="mt-2 text-sm text-[#e4e4e7]">
        {values?.length ? values.slice(0, 4).join(", ") : "Not detected"}
      </div>
    </div>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[#71717a]">{label}</span>
      <span className="truncate text-right text-[#e4e4e7]">{value}</span>
    </div>
  );
}

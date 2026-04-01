"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { loadProfileOptions, PROFILE_OPTIONS_FALLBACK } from "@/lib/profile-options";
import { makeQueuedRun, upsertRunCaches } from "@/lib/run-cache";
import { Upload } from "lucide-react";

type MultiSelectProps = {
  label: string;
  options: string[];
  selected: string[];
  onChange: (val: string[]) => void;
};

function MultiSelect({ label, options, selected, onChange }: MultiSelectProps) {
  const toggle = (opt: string) => {
    onChange(
      selected.includes(opt) ? selected.filter((x) => x !== opt) : [...selected, opt]
    );
  };
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] text-[#71717a] uppercase tracking-wider">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = selected.includes(opt);
          return (
            <button
              key={opt}
              type="button"
              onClick={() => toggle(opt)}
              className={`px-2.5 py-1 text-[11px] border transition-colors ${
                active
                  ? "border-[#22c55e] text-[#22c55e] bg-[#22c55e]/10"
                  : "border-[#3f3f46] text-[#71717a] hover:border-[#52525b]"
              }`}
            >
              {active ? "✓ " : ""}{opt}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function OnboardingPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const token = (session as { accessToken?: string })?.accessToken ?? "";

  const [step, setStep] = useState<"upload" | "preferences">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Preferences state
  const [parsing, setParsing] = useState(false);
  const [targetRoles, setTargetRoles] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [roleOptions, setRoleOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.role_options);
  const [locationOptions, setLocationOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.location_options);
  const [exclusions, setExclusions] = useState("");
  const [salaryLpa, setSalaryLpa] = useState("");
  const [minYoe, setMinYoe] = useState("");
  const [maxYoe, setMaxYoe] = useState("");

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function stopPolling() {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => () => stopPolling(), []);

  useEffect(() => {
    if (!token) return;
    loadProfileOptions(token).then((options) => {
      setRoleOptions(options.role_options);
      setLocationOptions(options.location_options);
    });
  }, [token]);

  const startPolling = useCallback(() => {
    stopPolling();
    let delay = 2500;
    const maxDelay = 30000;

    const schedule = () => {
      pollRef.current = setTimeout(async () => {
        try {
          const res = await api.onboarding.parsed(token);
          if (!res.parsing) {
            stopPolling();
            setParsing(false);
            const p = res.prefill;
            if (p.target_roles?.length) setTargetRoles(p.target_roles);
            if (p.preferred_locations?.length) setLocations(p.preferred_locations);
            if (p.exclusions?.length) setExclusions(p.exclusions.join(", "));
            if (p.salary_lpa) setSalaryLpa(String(p.salary_lpa));
            if (p.min_yoe != null) setMinYoe(String(p.min_yoe));
            if (p.max_yoe != null) setMaxYoe(String(p.max_yoe));
            return;
          }
        } catch {
          // ignore transient errors
        }
        delay = Math.min(delay * 2, maxDelay);
        schedule();
      }, delay);
    };

    schedule();
  }, [token]);

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await api.onboarding.uploadResume(token, file);
      setParsing(true);
      setStep("preferences");
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleFinish(e: React.FormEvent) {
    e.preventDefault();
    stopPolling();
    setSubmitting(true);
    try {
      if (targetRoles.length)
        await api.onboarding.refine(token, "target_roles", targetRoles);
      if (locations.length)
        await api.onboarding.refine(token, "preferred_locations", locations);
      if (exclusions.trim())
        await api.onboarding.refine(
          token,
          "exclusions",
          exclusions.split(",").map((s) => s.trim()).filter(Boolean)
        );
      if (salaryLpa.trim())
        await api.onboarding.refine(token, "salary_expectations", salaryLpa);
      if (minYoe.trim() || maxYoe.trim()) {
        await api.profile.patch(token, {
          min_yoe: minYoe.trim() ? Number(minYoe) : null,
          max_yoe: maxYoe.trim() ? Number(maxYoe) : null,
        });
      }
      await api.onboarding.refine(token, "onboarding_complete", "true");
      const res = await api.runs.trigger(token);
      upsertRunCaches(makeQueuedRun(res.run_id));
      router.push("/dashboard");
    } finally {
      setSubmitting(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] px-4">
      <div className="w-full max-w-lg space-y-6">

        <div className="text-center space-y-1">
          <div className="text-2xl font-bold text-[#22c55e] text-glow-green tracking-widest">
            SIGNAL<span className="text-[#a3e635]">RANK</span>
          </div>
          <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
            Setup Wizard
          </div>
        </div>

        <div className="flex items-center gap-0">
          {["UPLOAD RESUME", "PREFERENCES"].map((label, i) => {
            const currentStep = step === "upload" ? 0 : 1;
            const active = i === currentStep;
            const done = i < currentStep;
            return (
              <div key={i} className="flex items-center flex-1">
                <div className={`flex items-center gap-2 text-[10px] uppercase tracking-wider ${
                  active ? "text-[#22c55e]" : done ? "text-[#52525b]" : "text-[#3f3f46]"
                }`}>
                  <span className={`w-5 h-5 flex items-center justify-center border text-[9px] font-bold ${
                    active ? "border-[#22c55e] text-[#22c55e]" : done ? "border-[#52525b] text-[#52525b]" : "border-[#3f3f46] text-[#3f3f46]"
                  }`}>
                    {done ? "✓" : i + 1}
                  </span>
                  {label}
                </div>
                {i < 1 && <div className={`flex-1 h-px mx-3 ${done ? "bg-[#52525b]" : "bg-[#27272a]"}`} />}
              </div>
            );
          })}
        </div>

        <div className="border border-[#3f3f46] bg-[#18181b] p-6">
          {step === "upload" ? (
            <form onSubmit={handleUpload} className="space-y-5">
              <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
                {"// [1/2] UPLOAD RESUME"}
              </div>

              <label
                className={`block border-2 border-dashed p-8 text-center cursor-pointer transition-colors ${
                  dragging
                    ? "border-[#22c55e] bg-[#22c55e]/5"
                    : file
                    ? "border-[#22c55e]/60 bg-[#22c55e]/5"
                    : "border-[#3f3f46] hover:border-[#52525b]"
                }`}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
              >
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="hidden"
                />
                <div className="space-y-2">
                  <Upload size={20} className={file ? "text-[#22c55e] mx-auto" : "text-[#52525b] mx-auto"} />
                  {file ? (
                    <div>
                      <div className="text-xs text-[#22c55e]">{file.name}</div>
                      <div className="text-[10px] text-[#52525b]">
                        {(file.size / 1024).toFixed(0)} KB
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="text-xs text-[#71717a]">Drop resume here or click to browse</div>
                      <div className="text-[10px] text-[#52525b] mt-1">PDF · DOCX · TXT</div>
                    </div>
                  )}
                </div>
              </label>

              {error && (
                <div className="text-[11px] text-[#ef4444]">&gt; ERR: {error}</div>
              )}

              <button
                type="submit"
                disabled={uploading || !file}
                className="w-full py-2.5 text-xs font-bold uppercase tracking-widest bg-[#22c55e] text-[#0a0a0a] hover:bg-[#a3e635] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {uploading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="inline-block w-1 h-3 bg-[#0a0a0a] animate-pulse" />
                    Parsing
                    <span className="tracking-widest">...</span>
                  </span>
                ) : "Parse Resume"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleFinish} className="space-y-5">
              <div className="flex items-center justify-between">
                <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
                  {"// [2/2] PREFERENCES"}
                </div>
                {parsing && (
                  <div className="text-[10px] text-[#a3e635] animate-pulse uppercase tracking-widest">
                    AI analyzing resume...
                  </div>
                )}
              </div>

              <MultiSelect
                label="Target roles"
                options={roleOptions}
                selected={targetRoles}
                onChange={setTargetRoles}
              />

              <MultiSelect
                label="Preferred locations"
                options={locationOptions}
                selected={locations}
                onChange={setLocations}
              />

              <div className="space-y-1.5">
                <label className="text-[10px] text-[#71717a] uppercase tracking-wider">
                  Salary expectation (LPA)
                </label>
                <div className="flex items-center border border-[#3f3f46] bg-[#0a0a0a] focus-within:border-[#22c55e] transition-colors">
                  <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                  <input
                    value={salaryLpa}
                    onChange={(e) => setSalaryLpa(e.target.value)}
                    className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                    placeholder="e.g. 30"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] text-[#71717a] uppercase tracking-wider">
                  Experience range
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex items-center border border-[#3f3f46] bg-[#0a0a0a] focus-within:border-[#22c55e] transition-colors">
                    <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                    <input
                      value={minYoe}
                      onChange={(e) => setMinYoe(e.target.value)}
                      className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                      placeholder="Min YOE"
                      inputMode="numeric"
                    />
                  </div>
                  <div className="flex items-center border border-[#3f3f46] bg-[#0a0a0a] focus-within:border-[#22c55e] transition-colors">
                    <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                    <input
                      value={maxYoe}
                      onChange={(e) => setMaxYoe(e.target.value)}
                      className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                      placeholder="Max YOE"
                      inputMode="numeric"
                    />
                  </div>
                </div>
                <div className="text-[10px] text-[#71717a] leading-relaxed">
                  We prefill role and experience from your resume. You can fine-tune both anytime in Settings after setup.
                </div>
              </div>

              <div className="border-l-2 border-[#22c55e]/30 pl-3 text-[11px] leading-relaxed text-[#a1a1aa]">
                The scrape window lives in Settings. Keep it small for quick refreshes, or expand it later if you want older jobs included in future scans.
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] text-[#71717a] uppercase tracking-wider">
                  Roles / companies to exclude
                </label>
                <div className="flex items-center border border-[#3f3f46] bg-[#0a0a0a] focus-within:border-[#22c55e] transition-colors">
                  <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                  <input
                    value={exclusions}
                    onChange={(e) => setExclusions(e.target.value)}
                    className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                    placeholder="e.g. QA Engineer, Support, Consulting"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 text-xs font-bold uppercase tracking-widest bg-[#22c55e] text-[#0a0a0a] hover:bg-[#a3e635] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {submitting ? "Setting up..." : "Finish Setup →"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

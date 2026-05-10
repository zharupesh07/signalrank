"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  CheckCircle,
  Database,
  FileText,
  Info,
  RefreshCw,
  Save,
  Shield,
  Target,
  User,
} from "lucide-react";

import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import { ResumeEditorComponent, sanitizeResumeEditor, validateResumeEditor } from "@/components/settings/resume-editor";
import { SearchConfig } from "@/components/settings/search-config";
import { RecruiterFinder } from "@/components/settings/recruiter-finder";
import { api } from "@/lib/api";
import { formatPenaltyPattern } from "@/lib/formatting";
import { swr } from "@/lib/cache";
import { loadProfileOptions, PROFILE_OPTIONS_FALLBACK } from "@/lib/profile-options";
import { makeQueuedRun, upsertRunCaches } from "@/lib/run-cache";
import type { Profile, ProfileScanPlan, ResumeEditor, Run } from "@/types";

const EMPTY_RESUME_EDITOR: ResumeEditor = {
  name: "",
  position: "",
  email: "",
  phone: "",
  location: "",
  linkedin: "",
  github: "",
  website: "",
  summary: "",
  experiences: [],
  projects: [],
  skills: [],
  certifications: [],
};

function serializeSettingsSnapshot(input: {
  targetRoles: string[];
  locations: string[];
  customQueries: string[];
  targetLpa: string;
  minYoe: string;
  maxYoe: string;
  scraperHoursOld: string;
  scraperMaxTerms: string;
  resumeTemplate: string;
  resumeEditor: ResumeEditor;
}) {
  return JSON.stringify({
    ...input,
    resumeEditor: sanitizeResumeEditor(input.resumeEditor),
  });
}

function sectionButtonClass(active: boolean) {
  return [
    "flex w-full items-center gap-2 border px-3 py-2 text-left text-[11px] uppercase tracking-[0.18em] transition-colors",
    active
      ? "border-primary bg-primary/10 text-primary"
      : "border-border bg-card text-muted-foreground hover:border-primary/30 hover:text-foreground",
  ].join(" ");
}

type SettingsSection = "profile" | "resume" | "search" | "recruiters" | "developer";

export default function SettingsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const isAdmin = (session as { isAdmin?: boolean })?.isAdmin ?? false;
  const isDev = process.env.NODE_ENV === "development" && isAdmin;
  const { toast } = useToast();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [triggeringDeepScan, setTriggeringDeepScan] = useState(false);
  const [activeSection, setActiveSection] = useState<SettingsSection>("resume");

  const [targetRoles, setTargetRoles] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [customQueries, setCustomQueries] = useState<string[]>([]);
  const [targetLpa, setTargetLpa] = useState("");
  const [minYoe, setMinYoe] = useState("");
  const [maxYoe, setMaxYoe] = useState("");
  const [scraperHoursOld, setScraperHoursOld] = useState("");
  const [scraperMaxTerms, setScraperMaxTerms] = useState("");
  const [resumeTemplate, setResumeTemplate] = useState("classic");
  const [resumeTemplates, setResumeTemplates] = useState<string[]>(["classic", "minimal", "modern"]);
  const [resumeEditor, setResumeEditor] = useState<ResumeEditor>(EMPTY_RESUME_EDITOR);

  const [roleOptions, setRoleOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.role_options);
  const [locationOptions, setLocationOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.location_options);
  const [titlePenaltyRules, setTitlePenaltyRules] = useState(PROFILE_OPTIONS_FALLBACK.title_penalty_rules);
  const [scanPlan, setScanPlan] = useState<ProfileScanPlan | null>(PROFILE_OPTIONS_FALLBACK.scan_plan);

  const [initialTierSS, setInitialTierSS] = useState<string[]>([]);
  const [initialTierS, setInitialTierS] = useState<string[]>([]);
  const [initialPenaltyStrong, setInitialPenaltyStrong] = useState<string[]>([]);
  const [initialPenaltyAdjacent, setInitialPenaltyAdjacent] = useState<string[]>([]);
  const [initialPenaltyHybrid, setInitialPenaltyHybrid] = useState<string[]>([]);

  const [dbInfo, setDbInfo] = useState<{ target: string; railway_available: boolean; db_host: string } | null>(null);
  const [switchingDb, setSwitchingDb] = useState(false);

  const loaded = useRef(false);
  const snapshotRef = useRef("");

  const load = useCallback(async () => {
    if (!token) return;
    const p = await api.profile.get(token);
    const nextEditor = sanitizeResumeEditor(p.resume_editor ?? EMPTY_RESUME_EDITOR);
    setProfile(p);
    setTargetRoles(p.target_roles ?? []);
    setLocations(p.preferred_locations ?? []);
    setCustomQueries(p.custom_search_queries ?? []);
    setTargetLpa(p.target_lpa != null ? String(p.target_lpa) : "");
    setMinYoe(p.min_yoe != null ? String(p.min_yoe) : "");
    setMaxYoe(p.max_yoe != null ? String(p.max_yoe) : "");
    setScraperHoursOld(p.scraper_hours_old != null ? String(p.scraper_hours_old) : "");
    setScraperMaxTerms(p.scraper_max_terms != null ? String(p.scraper_max_terms) : "");
    setResumeTemplate(p.resume_template ?? "classic");
    setResumeEditor(nextEditor);
    snapshotRef.current = serializeSettingsSnapshot({
      targetRoles: p.target_roles ?? [],
      locations: p.preferred_locations ?? [],
      customQueries: p.custom_search_queries ?? [],
      targetLpa: p.target_lpa != null ? String(p.target_lpa) : "",
      minYoe: p.min_yoe != null ? String(p.min_yoe) : "",
      maxYoe: p.max_yoe != null ? String(p.max_yoe) : "",
      scraperHoursOld: p.scraper_hours_old != null ? String(p.scraper_hours_old) : "",
      scraperMaxTerms: p.scraper_max_terms != null ? String(p.scraper_max_terms) : "",
      resumeTemplate: p.resume_template ?? "classic",
      resumeEditor: nextEditor,
    });
    setDirty(false);
    loaded.current = true;
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await load();
      } catch (error) {
        if (!cancelled) {
          toast(error instanceof Error ? error.message : "Failed to load settings", "error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [load, toast]);

  useEffect(() => {
    let cancelled = false;
    if (!token) return;
    loadProfileOptions(token)
      .then((options) => {
        if (cancelled) return;
        setRoleOptions(options.role_options);
        setLocationOptions(options.location_options);
        setScanPlan(options.scan_plan);
        setTitlePenaltyRules(options.title_penalty_rules);
        setInitialTierSS(options.company_tier_lists.tier_ss);
        setInitialTierS(options.company_tier_lists.tier_s);
        setInitialPenaltyStrong(options.title_penalty_rules.strong.map(formatPenaltyPattern));
        setInitialPenaltyAdjacent(options.title_penalty_rules.adjacent.map(formatPenaltyPattern));
        setInitialPenaltyHybrid(options.title_penalty_rules.hybrid.map(formatPenaltyPattern));
      })
      .catch(() => {
        if (!cancelled) {
          toast("Failed to load profile options", "error");
        }
      });
    api.resume.templates(token)
      .then((res) => {
        if (!cancelled) {
          setResumeTemplates(res.templates);
        }
      })
      .catch(() => null);

    return () => { cancelled = true; };
  }, [token, toast]);

  useEffect(() => {
    if (!token) {
      setRun(null);
      return;
    }
    swr("dash:run", () => api.runs.latest(token), setRun);
  }, [token]);

  const currentSnapshot = useMemo(
    () =>
      serializeSettingsSnapshot({
        targetRoles,
        locations,
        customQueries,
        targetLpa,
        minYoe,
        maxYoe,
        scraperHoursOld,
        scraperMaxTerms,
        resumeTemplate,
        resumeEditor,
      }),
    [
      customQueries,
      locations,
      maxYoe,
      minYoe,
      resumeEditor,
      resumeTemplate,
      scraperHoursOld,
      scraperMaxTerms,
      targetLpa,
      targetRoles,
    ]
  );

  useEffect(() => {
    if (!loaded.current) return;
    setDirty(currentSnapshot !== snapshotRef.current);
  }, [currentSnapshot]);

  async function save() {
    if (!token) return false;
    const cleanedEditor = sanitizeResumeEditor(resumeEditor);
    const error = validateResumeEditor(cleanedEditor);
    if (error) {
      setActiveSection("resume");
      toast(error, "error");
      return false;
    }

    setSaving(true);
    setSaved(false);
    try {
      await api.profile.patch(token, {
        target_roles: targetRoles,
        preferred_locations: locations,
        custom_search_queries: customQueries,
        target_lpa: targetLpa ? Number(targetLpa) : null,
        min_yoe: minYoe ? Number(minYoe) : null,
        max_yoe: maxYoe ? Number(maxYoe) : null,
        scraper_hours_old: scraperHoursOld ? Number(scraperHoursOld) : null,
        scraper_max_terms: scraperMaxTerms ? Number(scraperMaxTerms) : null,
        resume_editor: cleanedEditor,
        config_overrides: { resume: { template: resumeTemplate } },
      });
      setResumeEditor(cleanedEditor);
      snapshotRef.current = serializeSettingsSnapshot({
        targetRoles,
        locations,
        customQueries,
        targetLpa,
        minYoe,
        maxYoe,
        scraperHoursOld,
        scraperMaxTerms,
        resumeTemplate,
        resumeEditor: cleanedEditor,
      });
      setDirty(false);
      setSaved(true);
      toast("Settings saved", "success");
      setTimeout(() => setSaved(false), 2000);
      await load();
      return true;
    } catch {
      toast("Save failed", "error");
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function loadDbInfo() {
    try {
      const info = await api.dev.getDb(token);
      setDbInfo(info);
    } catch {
      // Not in dev mode or endpoint unavailable
    }
  }

  async function handleSwitchDb(target: string) {
    setSwitchingDb(true);
    try {
      const info = await api.dev.switchDb(token, target);
      setDbInfo(info);
      toast(`Switched to ${target} DB (${info.db_host})`, "success");
    } catch (e) {
      toast(`Switch failed: ${e instanceof Error ? e.message : "unknown error"}`, "error");
    } finally {
      setSwitchingDb(false);
    }
  }

  async function triggerDeepScan() {
    if (!token) return;
    setTriggeringDeepScan(true);
    const optimisticRun = makeQueuedRun(`local-${Date.now()}`);
    try {
      const ok = dirty ? await save() : true;
      if (!ok) return;
      setRun(optimisticRun);
      const res = await api.runs.trigger(token, "full");
      const queuedRun = makeQueuedRun(res.run_id);
      setRun(queuedRun);
      upsertRunCaches(queuedRun);
      toast("Deep scan queued", "success");
    } catch {
      setRun((current) => (current?.id === optimisticRun.id ? null : current));
      toast("Failed to queue deep scan", "error");
    } finally {
      setTriggeringDeepScan(false);
    }
  }

  useEffect(() => {
    if (activeSection === "developer" && isDev) {
      loadDbInfo();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection]);

  const navItems: { id: SettingsSection; label: string; icon: typeof User }[] = [
    { id: "profile", label: "Profile", icon: User },
    { id: "resume", label: "Resume", icon: FileText },
    { id: "search", label: "Search", icon: Target },
    ...(isAdmin
      ? [{ id: "recruiters" as SettingsSection, label: "Recruiters", icon: Shield }]
      : []),
    ...(isDev
      ? [{ id: "developer" as SettingsSection, label: "Developer", icon: Database }]
      : []),
  ];

  return (
    <div className="page-content min-h-screen pt-14">
      <div className="mx-auto max-w-7xl px-6 py-8">
        <div className="space-y-1">
          <div className="section-label">settings</div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Configuration</h1>
        </div>

        <div className="mt-6 grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
          <aside className="space-y-3">
            <div className="space-y-2">
              {navItems.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActiveSection(id)}
                  className={sectionButtonClass(activeSection === id)}
                >
                  <Icon size={13} />
                  <span>{label}</span>
                </button>
              ))}
            </div>

            <div className="rounded-none border border-border bg-card p-4 text-[11px] text-muted-foreground">
              <div className="mb-1 flex items-center gap-2 uppercase tracking-[0.18em] text-primary">
                <Info size={11} />
                Notes
              </div>
              <div className="leading-relaxed">
                Resume text fields accept `**bold**` markers. Experience bullets and certifications are optional, but each experience row still needs title and company when present.
              </div>
            </div>
          </aside>

          <main className="space-y-6">
            {run && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="section-label">scan status</div>
                  <span className="text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                    updates live without refresh
                  </span>
                </div>
                <RunProgress
                  run={run}
                  onComplete={(completed) => {
                    setRun(completed);
                    upsertRunCaches(completed);
                  }}
                />
              </div>
            )}

            {activeSection === "profile" && (
              <div className="tab-enter space-y-6">
                <div className="stat-card card-hover space-y-5 border border-border bg-card p-5">
                  <div className="flex items-center gap-2">
                    <User size={13} className="text-primary" />
                    <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Profile</span>
                  </div>

                  {profile && (
                    <div className="flex items-center gap-4">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center border border-primary/30 bg-primary/5">
                        <span className="text-sm font-bold text-primary">{profile.email[0].toUpperCase()}</span>
                      </div>
                      <div>
                        <div className="text-xs font-medium text-foreground">{profile.email}</div>
                        <div className="mt-0.5 flex items-center gap-1.5">
                          {profile.onboarding_complete ? (
                            <>
                              <CheckCircle size={9} className="text-primary" />
                              <span className="text-[10px] text-primary">Onboarding complete</span>
                            </>
                          ) : (
                            <>
                              <Shield size={9} className="text-terminal-yellow" />
                              <span className="text-[10px] text-terminal-yellow">Onboarding incomplete</span>
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="grid gap-3 md:grid-cols-3">
                    {[
                      { label: "Target LPA", value: targetLpa, set: setTargetLpa, placeholder: "60", suffix: "L" },
                      { label: "Min YOE", value: minYoe, set: setMinYoe, placeholder: "3", suffix: "yr" },
                      { label: "Max YOE", value: maxYoe, set: setMaxYoe, placeholder: "12", suffix: "yr" },
                    ].map(({ label, value, set, placeholder, suffix }) => (
                      <div key={label}>
                        <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">{label}</label>
                        <div className="relative">
                          <input
                            type="number"
                            value={value}
                            onChange={(e) => set(e.target.value)}
                            placeholder={placeholder}
                            suppressHydrationWarning
                            className="w-full border border-border bg-input px-3 py-2 pr-10 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                          />
                          <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">{suffix}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {activeSection === "resume" && (
              <ResumeEditorComponent
                token={token}
                resumeEditor={resumeEditor}
                setResumeEditor={setResumeEditor}
                resumeTemplate={resumeTemplate}
                setResumeTemplate={setResumeTemplate}
                resumeTemplates={resumeTemplates}
                onLoad={load}
              />
            )}

            {activeSection === "search" && (
              <SearchConfig
                token={token}
                targetRoles={targetRoles}
                setTargetRoles={setTargetRoles}
                locations={locations}
                setLocations={setLocations}
                customQueries={customQueries}
                setCustomQueries={setCustomQueries}
                roleOptions={roleOptions}
                locationOptions={locationOptions}
                scraperHoursOld={scraperHoursOld}
                setScraperHoursOld={setScraperHoursOld}
                scraperMaxTerms={scraperMaxTerms}
                setScraperMaxTerms={setScraperMaxTerms}
                titlePenaltyRules={titlePenaltyRules}
                scanPlan={scanPlan}
                initialTierSS={initialTierSS}
                initialTierS={initialTierS}
                initialPenaltyStrong={initialPenaltyStrong}
                initialPenaltyAdjacent={initialPenaltyAdjacent}
                initialPenaltyHybrid={initialPenaltyHybrid}
                triggerDeepScan={triggerDeepScan}
                triggeringDeepScan={triggeringDeepScan}
                saving={saving}
              />
            )}

            {activeSection === "recruiters" && isAdmin && (
              <RecruiterFinder token={token} />
            )}

            {activeSection === "developer" && isDev && (
              <div className="tab-enter space-y-4">
                <div className="stat-card border border-border bg-card p-5 space-y-4">
                  <div className="flex items-center gap-2">
                    <Database size={13} className="text-primary" />
                    <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Database Target</span>
                  </div>
                  {dbInfo ? (
                    <>
                      <div className="space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] text-muted-foreground">Active</span>
                          <span className="text-[11px] font-medium text-foreground capitalize">{dbInfo.target}</span>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] text-muted-foreground">Host</span>
                          <span className="text-[11px] font-mono text-foreground truncate max-w-[220px]">{dbInfo.db_host}</span>
                        </div>
                        {!dbInfo.railway_available && (
                          <p className="text-[10px] text-yellow-500 pt-1">DATABASE_URL_RAILWAY not configured</p>
                        )}
                      </div>
                      <div className="flex gap-2 pt-1">
                        {(["local", "railway"] as const).map((target) => (
                          <button
                            key={target}
                            type="button"
                            disabled={switchingDb || dbInfo.target === target || (target === "railway" && !dbInfo.railway_available)}
                            onClick={() => handleSwitchDb(target)}
                            className="flex items-center gap-1.5 border px-4 py-1.5 text-[11px] uppercase tracking-wider transition-all duration-150 disabled:opacity-40"
                            style={{
                              background: dbInfo.target === target ? "var(--primary)" : "transparent",
                              borderColor: dbInfo.target === target ? "var(--primary)" : "color-mix(in srgb, var(--primary) 40%, transparent)",
                              color: dbInfo.target === target ? "var(--primary-foreground)" : "var(--primary)",
                            }}
                          >
                            {switchingDb && dbInfo.target !== target ? (
                              <RefreshCw size={9} className="animate-spin" />
                            ) : null}
                            {target}
                          </button>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      <RefreshCw size={10} className="animate-spin" />
                      Loading...
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="flex items-center justify-end gap-3">
              <span className="text-[10px] text-muted-foreground">{dirty ? "Unsaved changes" : "Changes saved"}</span>
              <button
                type="button"
                onClick={save}
                disabled={saving || triggeringDeepScan || !dirty}
                className="flex items-center gap-2 border px-5 py-2 text-[11px] uppercase tracking-wider transition-all duration-150 disabled:opacity-50"
                style={{
                  background: saved ? "var(--primary)" : dirty ? "transparent" : "color-mix(in srgb, var(--primary) 10%, transparent)",
                  borderColor: saved || dirty ? "var(--primary)" : "color-mix(in srgb, var(--primary) 25%, transparent)",
                  color: saved ? "var(--primary-foreground)" : "var(--primary)",
                }}
              >
                {saving ? (
                  <>
                    <RefreshCw size={10} className="animate-spin" />
                    Saving...
                  </>
                ) : !dirty ? (
                  <>
                    <CheckCircle size={10} />
                    Saved
                  </>
                ) : saved ? (
                  <>
                    <CheckCircle size={10} />
                    Saved
                  </>
                ) : (
                  <>
                    <Save size={10} />
                    Save
                  </>
                )}
              </button>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

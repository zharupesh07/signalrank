"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import {
  Briefcase,
  CheckCircle,
  Database,
  Eye,
  FileText,
  Info,
  Play,
  RefreshCw,
  Save,
  Search,
  Shield,
  Target,
  Upload,
  User,
} from "lucide-react";

import { TagInput } from "@/components/tag-input";
import { DraggableTagList } from "@/components/draggable-tag-list";
import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import { api } from "@/lib/api";
import { swr } from "@/lib/cache";
import { loadProfileOptions, PROFILE_OPTIONS_FALLBACK } from "@/lib/profile-options";
import { makeQueuedRun, upsertRunCaches } from "@/lib/run-cache";
import type {
  Profile,
  ResumeEditor,
  ResumeEditorExperience,
  Run,
} from "@/types";

interface RecruiterRow {
  id: string;
  company: string;
  name: string | null;
  email: string | null;
  linkedin_url: string | null;
  domain: string | null;
}

interface FoundRecruiter {
  name: string | null;
  email: string | null;
  linkedin_url: string;
  domain: string | null;
  confidence: string;
}

type SettingsSection = "profile" | "resume" | "search" | "recruiters" | "developer";

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

function dedupeStrings(values: string[]) {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const cleaned = value.trim();
    if (!cleaned) continue;
    const key = cleaned.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}

function sanitizeResumeEditor(editor: ResumeEditor): ResumeEditor {
  return {
    name: editor.name.trim(),
    position: editor.position.trim(),
    email: editor.email.trim(),
    phone: editor.phone.trim(),
    location: editor.location.trim(),
    linkedin: editor.linkedin.trim(),
    github: editor.github.trim(),
    website: editor.website.trim(),
    summary: editor.summary.trim(),
    experiences: editor.experiences
      .map((exp) => ({
        title: exp.title.trim(),
        company: exp.company.trim(),
        dates: exp.dates.trim(),
        location: exp.location.trim(),
        bullets: dedupeStrings(exp.bullets.map((bullet) => bullet.replace(/^[*\-•]\s*/, ""))),
      }))
      .filter((exp) => exp.title || exp.company || exp.dates || exp.location || exp.bullets.length > 0),
    projects: editor.projects
      .map((project) => ({
        name: project.name.trim(),
        url: project.url.trim(),
        description: project.description.trim(),
      }))
      .filter((project) => project.name || project.url || project.description),
    skills: editor.skills
      .map((group) => ({
        category: group.category.trim(),
        items: dedupeStrings(group.items),
      }))
      .filter((group) => group.category || group.items.length > 0),
    certifications: dedupeStrings(editor.certifications.map((item) => item.replace(/^[*\-•]\s*/, ""))),
  };
}

function looksLikeUrl(value: string) {
  const trimmed = value.trim();
  return (
    !trimmed ||
    trimmed.startsWith("http://") ||
    trimmed.startsWith("https://") ||
    trimmed.startsWith("www.") ||
    (trimmed.includes(".") && !trimmed.includes(" "))
  );
}

function validateResumeEditor(editor: ResumeEditor): string | null {
  if (editor.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(editor.email)) {
    return "Resume email must be valid.";
  }
  for (const field of [editor.linkedin, editor.github, editor.website]) {
    if (field && !looksLikeUrl(field)) {
      return "LinkedIn, GitHub, and website must look like public URLs.";
    }
  }
  for (const exp of editor.experiences) {
    const hasContent = Boolean(exp.title || exp.company || exp.dates || exp.location || exp.bullets.length);
    if (!hasContent) continue;
    if (!exp.title) return "Each experience entry needs a title.";
    if (!exp.company) return "Each experience entry needs a company.";
  }
  for (const project of editor.projects) {
    const hasContent = Boolean(project.name || project.url || project.description);
    if (!hasContent) continue;
    if (!project.name) return "Each project entry needs a name.";
    if (project.url && !looksLikeUrl(project.url)) {
      return "Project URLs must look like public URLs.";
    }
  }
  for (const skill of editor.skills) {
    const hasContent = Boolean(skill.category || skill.items.length);
    if (!hasContent) continue;
    if (!skill.category) return "Each skill group needs a category.";
    if (!skill.items.length) return "Each skill group needs at least one item.";
  }
  return null;
}

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

function formatPenaltyPattern(pattern: string) {
  return pattern
    .replace(/\\b/g, "")
    .replace(/\\s\+/g, " ")
    .replace(/\\/g, "")
    .trim();
}

function MetaListCard({
  title,
  tone,
  items,
  emptyLabel,
}: {
  title: string;
  tone: string;
  items: string[];
  emptyLabel: string;
}) {
  return (
    <div className="space-y-2 border border-border bg-background/40 p-4">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{title}</div>
        <div className={`text-[10px] tabular-nums ${tone}`}>{items.length}</div>
      </div>
      {items.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <span
              key={`${title}-${item}`}
              className={`border px-2 py-1 text-[11px] ${tone} border-current/20 bg-current/5`}
            >
              {item}
            </span>
          ))}
        </div>
      ) : (
        <div className="text-[11px] text-muted-foreground">{emptyLabel}</div>
      )}
    </div>
  );
}

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
  const [previewingResume, setPreviewingResume] = useState(false);
  const [uploadingResume, setUploadingResume] = useState(false);
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
  const [companyTierLists, setCompanyTierLists] = useState(PROFILE_OPTIONS_FALLBACK.company_tier_lists);

  // Editable copies for drag-drop UI
  const [editTierSS, setEditTierSS] = useState<string[]>([]);
  const [editTierS, setEditTierS] = useState<string[]>([]);
  const [editPenaltyStrong, setEditPenaltyStrong] = useState<string[]>([]);
  const [editPenaltyAdjacent, setEditPenaltyAdjacent] = useState<string[]>([]);
  const [editPenaltyHybrid, setEditPenaltyHybrid] = useState<string[]>([]);
  const [savingRankingConfig, setSavingRankingConfig] = useState(false);

  const [findCompany, setFindCompany] = useState("");
  const [findDomain, setFindDomain] = useState("");
  const [finding, setFinding] = useState(false);
  const [foundRecruiters, setFoundRecruiters] = useState<FoundRecruiter[]>([]);
  const [allRecruiters, setAllRecruiters] = useState<RecruiterRow[]>([]);
  const [recruiterCompanyFilter, setRecruiterCompanyFilter] = useState("");

  const [dbInfo, setDbInfo] = useState<{ target: string; railway_available: boolean; db_host: string } | null>(null);
  const [switchingDb, setSwitchingDb] = useState(false);

  const loaded = useRef(false);
  const snapshotRef = useRef("");
  const resumeUploadRef = useRef<HTMLInputElement | null>(null);

  const loadRecruiters = useCallback(async () => {
    if (!token) return;
    const recs = await api.recruiters.list(token);
    setAllRecruiters(recs);
  }, [token]);

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

      try {
        await loadRecruiters();
      } catch {
        if (!cancelled) {
          toast("Failed to load recruiters", "error");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [load, loadRecruiters, toast]);

  useEffect(() => {
    let cancelled = false;
    if (!token) return;
    loadProfileOptions(token)
      .then((options) => {
        if (cancelled) return;
        setRoleOptions(options.role_options);
        setLocationOptions(options.location_options);
        setTitlePenaltyRules(options.title_penalty_rules);
        setCompanyTierLists(options.company_tier_lists);
        setEditTierSS(options.company_tier_lists.tier_ss);
        setEditTierS(options.company_tier_lists.tier_s);
        setEditPenaltyStrong(options.title_penalty_rules.strong.map(formatPenaltyPattern));
        setEditPenaltyAdjacent(options.title_penalty_rules.adjacent.map(formatPenaltyPattern));
        setEditPenaltyHybrid(options.title_penalty_rules.hybrid.map(formatPenaltyPattern));
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

    return () => {
      cancelled = true;
    };
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

  function toRegexPattern(plain: string): string {
    const escaped = plain.trim().replace(/\s+/g, "\\s+");
    return `\\b${escaped}\\b`;
  }

  async function saveRankingConfig() {
    if (!token) return;
    setSavingRankingConfig(true);
    try {
      await api.profile.patch(token, {
        config_overrides: {
          company_scoring: {
            tier_ss: editTierSS,
            tier_s: editTierS,
          },
          ranking: {
            profile_title_rules_override: {
              strong: editPenaltyStrong.map(toRegexPattern),
              adjacent: editPenaltyAdjacent.map(toRegexPattern),
              hybrid: editPenaltyHybrid.map(toRegexPattern),
            },
          },
        },
      });
      toast("Ranking config saved", "success");
    } catch {
      toast("Save failed", "error");
    } finally {
      setSavingRankingConfig(false);
    }
  }

  async function handlePreviewResume() {
    if (!token) return;
    const cleanedEditor = sanitizeResumeEditor(resumeEditor);
    const error = validateResumeEditor(cleanedEditor);
    if (error) {
      toast(error, "error");
      return;
    }
    setPreviewingResume(true);
    try {
      const preview = await api.resume.preview(token, {
        template: resumeTemplate,
        resume_editor: cleanedEditor,
      });
      const notices = [...preview.fit_actions, ...preview.warnings];
      if (notices.length > 0) {
        toast(`Preview opened with warnings: ${notices[0]}`, "info");
      } else {
        toast("Resume preview opened", "success");
      }
    } catch {
      toast("Preview failed", "error");
    } finally {
      setPreviewingResume(false);
    }
  }

  async function handleResumeUpload(file: File) {
    if (!token) return;
    setUploadingResume(true);
    try {
      await api.onboarding.uploadResume(token, file);
      await load();
      setActiveSection("resume");
      toast("Resume uploaded and parsed", "success");
    } catch {
      toast("Resume upload failed", "error");
    } finally {
      setUploadingResume(false);
      if (resumeUploadRef.current) {
        resumeUploadRef.current.value = "";
      }
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
    try {
      const ok = dirty ? await save() : true;
      if (!ok) return;
      const res = await api.runs.trigger(token, "full");
      const queuedRun = makeQueuedRun(res.run_id);
      setRun(queuedRun);
      upsertRunCaches(queuedRun);
      toast("Deep scan queued", "success");
    } catch {
      toast("Failed to queue deep scan", "error");
    } finally {
      setTriggeringDeepScan(false);
    }
  }

  async function findRecruiters() {
    if (!token || !findCompany.trim()) return;
    setFinding(true);
    setFoundRecruiters([]);
    try {
      const res = await api.recruiters.find(token, {
        company: findCompany.trim(),
        domain: findDomain.trim() || undefined,
        max_results: 10,
      });
      setFoundRecruiters(res.recruiters ?? []);
      toast(`Found ${res.found} recruiter(s), saved ${res.inserted} new`, "success");
      await loadRecruiters();
    } catch {
      toast("Recruiter search failed", "error");
    } finally {
      setFinding(false);
    }
  }

  useEffect(() => {
    if (activeSection === "developer" && isDev) {
      loadDbInfo();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSection]);

  const filteredRecruiters = recruiterCompanyFilter
    ? allRecruiters.filter((r) => r.company?.toLowerCase().includes(recruiterCompanyFilter.toLowerCase()))
    : allRecruiters;

  const navItems: { id: SettingsSection; label: string; icon: typeof User }[] = [
    { id: "profile", label: "Profile", icon: User },
    { id: "resume", label: "Resume", icon: FileText },
    { id: "search", label: "Search", icon: Target },
    { id: "recruiters", label: "Recruiters", icon: Briefcase },
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
              <div className="space-y-6">
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
              <div className="space-y-6">
                <div className="stat-card card-hover space-y-5 border border-border bg-card p-5">
                  <div className="flex items-center gap-2">
                    <FileText size={13} className="text-primary" />
                    <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Resume Content</span>
                  </div>

                  <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
                    <div>
                      <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                        Resume Theme
                      </label>
                      <select
                        value={resumeTemplate}
                        onChange={(e) => setResumeTemplate(e.target.value)}
                        suppressHydrationWarning
                        className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                      >
                        {resumeTemplates.map((template) => (
                          <option key={template} value={template}>
                            {template}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => resumeUploadRef.current?.click()}
                        disabled={uploadingResume}
                        className="inline-flex h-9 items-center gap-2 border border-primary/40 px-3 text-[10px] uppercase tracking-[0.22em] text-primary transition-colors hover:bg-primary/8 disabled:opacity-50"
                      >
                        {uploadingResume ? <RefreshCw size={10} className="animate-spin" /> : <Upload size={10} />}
                        {uploadingResume ? "Uploading..." : "Upload New Resume"}
                      </button>
                      <button
                        type="button"
                        onClick={handlePreviewResume}
                        disabled={previewingResume}
                        className="inline-flex h-9 items-center gap-2 border border-border px-3 text-[10px] uppercase tracking-[0.22em] text-foreground transition-colors hover:border-primary/30 hover:bg-primary/8 disabled:opacity-50"
                      >
                        {previewingResume ? <RefreshCw size={10} className="animate-spin" /> : <Eye size={10} />}
                        {previewingResume ? "Opening..." : "Preview Resume"}
                      </button>
                    </div>
                  </div>
                  <input
                    ref={resumeUploadRef}
                    type="file"
                    accept=".pdf,.doc,.docx,.txt"
                    className="hidden"
                    suppressHydrationWarning
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) handleResumeUpload(file);
                    }}
                  />

                  <div className="grid gap-3 md:grid-cols-2">
                    {[
                      ["Full Name", "name"],
                      ["Headline", "position"],
                      ["Email", "email"],
                      ["Phone", "phone"],
                      ["Location", "location"],
                      ["LinkedIn", "linkedin"],
                      ["GitHub", "github"],
                      ["Website", "website"],
                    ].map(([label, key]) => (
                      <div key={key}>
                        <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">{label}</label>
                        <input
                          type="text"
                          value={resumeEditor[key as keyof ResumeEditor] as string}
                          onChange={(e) =>
                            setResumeEditor((current) => ({
                              ...current,
                              [key]: e.target.value,
                            }))
                          }
                          suppressHydrationWarning
                          className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                        />
                      </div>
                    ))}
                  </div>

                  <div>
                    <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">Summary</label>
                    <textarea
                      rows={4}
                      value={resumeEditor.summary}
                      onChange={(e) => setResumeEditor((current) => ({ ...current, summary: e.target.value }))}
                      suppressHydrationWarning
                      className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                    />
                    <div className="mt-1 text-[10px] leading-relaxed text-muted-foreground/80">
                      Use `**bold**` for emphasis. Keep this tight; the preview will show whether the page has room for more later.
                    </div>
                  </div>

                  <div className="space-y-3 border-t border-border pt-4">
                    <div className="flex items-center justify-between">
                      <div className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Experience</div>
                      <button
                        type="button"
                        onClick={() =>
                          setResumeEditor((current) => ({
                            ...current,
                            experiences: [
                              ...current.experiences,
                              { title: "", company: "", dates: "", location: "", bullets: [""] },
                            ],
                          }))
                        }
                        className="text-[10px] uppercase tracking-[0.18em] text-primary"
                      >
                        Add Experience
                      </button>
                    </div>
                    {resumeEditor.experiences.length === 0 && (
                      <div className="text-[11px] text-muted-foreground">No experience rows yet. Upload a resume or add one manually.</div>
                    )}
                    {resumeEditor.experiences.map((experience, index) => (
                      <div key={`exp-${index}`} className="space-y-3 border border-border p-4">
                        <div className="grid gap-3 md:grid-cols-2">
                          {[
                            ["Title", "title"],
                            ["Company", "company"],
                            ["Dates", "dates"],
                            ["Location", "location"],
                          ].map(([label, key]) => (
                            <div key={key}>
                              <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">{label}</label>
                              <input
                                type="text"
                                value={experience[key as keyof ResumeEditorExperience] as string}
                                onChange={(e) =>
                                  setResumeEditor((current) => ({
                                    ...current,
                                    experiences: current.experiences.map((item, itemIndex) =>
                                      itemIndex === index ? { ...item, [key]: e.target.value } : item
                                    ),
                                  }))
                                }
                                suppressHydrationWarning
                                className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                              />
                            </div>
                          ))}
                        </div>
                        <div>
                          <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                            Bullets
                          </label>
                          <textarea
                            rows={5}
                            value={experience.bullets.join("\n")}
                            onChange={(e) =>
                              setResumeEditor((current) => ({
                                ...current,
                                experiences: current.experiences.map((item, itemIndex) =>
                                  itemIndex === index
                                    ? { ...item, bullets: e.target.value.split("\n") }
                                    : item
                                ),
                              }))
                            }
                            suppressHydrationWarning
                            className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                          />
                        </div>
                        <div className="flex justify-end">
                          <button
                            type="button"
                            onClick={() =>
                              setResumeEditor((current) => ({
                                ...current,
                                experiences: current.experiences.filter((_, itemIndex) => itemIndex !== index),
                              }))
                            }
                            className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground"
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="space-y-3 border-t border-border pt-4">
                    <div className="flex items-center justify-between">
                      <div className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Projects</div>
                      <button
                        type="button"
                        onClick={() =>
                          setResumeEditor((current) => ({
                            ...current,
                            projects: [...current.projects, { name: "", url: "", description: "" }],
                          }))
                        }
                        className="text-[10px] uppercase tracking-[0.18em] text-primary"
                      >
                        Add Project
                      </button>
                    </div>
                    {resumeEditor.projects.map((project, index) => (
                      <div key={`project-${index}`} className="space-y-3 border border-border p-4">
                        <div className="grid gap-3 md:grid-cols-2">
                          <div>
                            <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">Name</label>
                            <input
                              type="text"
                              value={project.name}
                              onChange={(e) =>
                                setResumeEditor((current) => ({
                                  ...current,
                                  projects: current.projects.map((item, itemIndex) =>
                                    itemIndex === index ? { ...item, name: e.target.value } : item
                                  ),
                                }))
                              }
                              suppressHydrationWarning
                              className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                            />
                          </div>
                          <div>
                            <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">URL</label>
                            <input
                              type="text"
                              value={project.url}
                              onChange={(e) =>
                                setResumeEditor((current) => ({
                                  ...current,
                                  projects: current.projects.map((item, itemIndex) =>
                                    itemIndex === index ? { ...item, url: e.target.value } : item
                                  ),
                                }))
                              }
                              suppressHydrationWarning
                              className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                            />
                          </div>
                        </div>
                        <div>
                          <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                            Description
                          </label>
                          <textarea
                            rows={3}
                            value={project.description}
                            onChange={(e) =>
                              setResumeEditor((current) => ({
                                ...current,
                                projects: current.projects.map((item, itemIndex) =>
                                  itemIndex === index ? { ...item, description: e.target.value } : item
                                ),
                              }))
                            }
                            suppressHydrationWarning
                            className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                          />
                        </div>
                        <div className="flex justify-end">
                          <button
                            type="button"
                            onClick={() =>
                              setResumeEditor((current) => ({
                                ...current,
                                projects: current.projects.filter((_, itemIndex) => itemIndex !== index),
                              }))
                            }
                            className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground"
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="space-y-3 border-t border-border pt-4">
                    <div className="flex items-center justify-between">
                      <div className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Skills</div>
                      <button
                        type="button"
                        onClick={() =>
                          setResumeEditor((current) => ({
                            ...current,
                            skills: [...current.skills, { category: "", items: [""] }],
                          }))
                        }
                        className="text-[10px] uppercase tracking-[0.18em] text-primary"
                      >
                        Add Skill Group
                      </button>
                    </div>
                    {resumeEditor.skills.map((group, index) => (
                      <div key={`skill-${index}`} className="space-y-3 border border-border p-4">
                        <div>
                          <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">Category</label>
                          <input
                            type="text"
                            value={group.category}
                            onChange={(e) =>
                              setResumeEditor((current) => ({
                                ...current,
                                skills: current.skills.map((item, itemIndex) =>
                                  itemIndex === index ? { ...item, category: e.target.value } : item
                                ),
                              }))
                            }
                            suppressHydrationWarning
                            className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                            Items
                          </label>
                          <textarea
                            rows={3}
                            value={group.items.join("\n")}
                            onChange={(e) =>
                              setResumeEditor((current) => ({
                                ...current,
                                skills: current.skills.map((item, itemIndex) =>
                                  itemIndex === index
                                    ? { ...item, items: e.target.value.split("\n") }
                                    : item
                                ),
                              }))
                            }
                            suppressHydrationWarning
                            className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                          />
                        </div>
                        <div className="flex justify-end">
                          <button
                            type="button"
                            onClick={() =>
                              setResumeEditor((current) => ({
                                ...current,
                                skills: current.skills.filter((_, itemIndex) => itemIndex !== index),
                              }))
                            }
                            className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground"
                          >
                            Remove
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="border-t border-border pt-4">
                    <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                      Certifications
                    </label>
                    <textarea
                      rows={4}
                      value={resumeEditor.certifications.join("\n")}
                      onChange={(e) =>
                        setResumeEditor((current) => ({
                          ...current,
                          certifications: e.target.value.split("\n"),
                        }))
                      }
                      suppressHydrationWarning
                      className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors focus:border-primary focus:outline-none"
                    />
                    <div className="mt-1 text-[10px] text-muted-foreground/80">
                      Optional. Keep one certification per line.
                    </div>
                  </div>
                </div>
              </div>
            )}

            {activeSection === "search" && (
              <div className="space-y-6">
                <div className="stat-card card-hover space-y-5 border border-border bg-card p-5">
                  <div className="flex items-center gap-2">
                    <Target size={13} className="text-primary" />
                    <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Search Preferences</span>
                  </div>

                  <TagInput
                    label="Target Roles"
                    value={targetRoles}
                    onChange={setTargetRoles}
                    placeholder="Add role, press Enter..."
                    suggestions={roleOptions}
                  />
                  <div className="mt-[-10px] text-[10px] leading-relaxed text-muted-foreground">
                    Add any title here, not just the suggestions. Type a custom role and press Enter or comma to include it in future scans.
                  </div>

                  <TagInput
                    label="Preferred Locations"
                    value={locations}
                    onChange={setLocations}
                    placeholder="Add location, press Enter..."
                    suggestions={locationOptions}
                  />

                  <TagInput
                    label="Custom Search Queries"
                    value={customQueries}
                    onChange={setCustomQueries}
                    placeholder="e.g. 'LLM platform engineer Bangalore'"
                  />
                </div>

                <div className="stat-card card-hover space-y-5 border border-border bg-card p-5">
                  <div className="flex items-center gap-2">
                    <RefreshCw size={13} className="text-primary" />
                    <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Scraping Config</span>
                  </div>
                  <p className="border-l-2 border-primary/20 pl-3 text-[10px] leading-relaxed text-muted-foreground">
                    Quick refresh uses Indeed only with 1 title and a 24h lookback. Full background runs use all roles and sources.
                    Raise the lookback here if you want the scraper to search further back in time.
                  </p>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                        Full Run Lookback (hours)
                      </label>
                      <div className="relative">
                        <input
                          type="number"
                          value={scraperHoursOld}
                          onChange={(e) => setScraperHoursOld(e.target.value)}
                          placeholder="168"
                          suppressHydrationWarning
                          className="w-full border border-border bg-input px-3 py-2 pr-10 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                        />
                        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">hrs</span>
                      </div>
                      <div className="mt-1 flex items-start gap-1.5 text-[10px] leading-relaxed text-muted-foreground/80">
                        <Info size={10} className="mt-0.5 shrink-0 text-primary" />
                        <span>Example: 168 = 7 days, 720 = 30 days. Higher values widen future scans.</span>
                      </div>
                    </div>
                    <div>
                      <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">
                        Full Run Max Titles
                      </label>
                      <input
                        type="number"
                        value={scraperMaxTerms}
                        onChange={(e) => setScraperMaxTerms(e.target.value)}
                        placeholder="all"
                        suppressHydrationWarning
                        className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                      />
                    </div>
                  </div>
                  <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-[11px] leading-relaxed text-muted-foreground">
                      Longer-duration and multi-title scans are only launched from here. The button below uses the saved lookback and title settings on this page.
                    </div>
                    <button
                      type="button"
                      onClick={triggerDeepScan}
                      disabled={triggeringDeepScan || saving}
                      className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 self-start border border-primary/40 px-3 text-[10px] uppercase tracking-[0.22em] text-primary transition-colors hover:bg-primary/8 disabled:opacity-50 sm:self-auto"
                    >
                      {triggeringDeepScan ? (
                        <>
                          <RefreshCw size={9} className="animate-spin" />
                          Queuing...
                        </>
                      ) : (
                        <>
                          <Play size={9} />
                          Deep Scan
                        </>
                      )}
                    </button>
                  </div>
                </div>

                <div className="stat-card card-hover space-y-5 border border-border bg-card p-5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Info size={13} className="text-primary" />
                      <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Title Penalties</span>
                    </div>
                    <button
                      type="button"
                      onClick={saveRankingConfig}
                      disabled={savingRankingConfig}
                      className="flex items-center gap-1.5 px-3 py-1 text-[11px] border border-primary/30 text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
                    >
                      <Save size={10} />
                      {savingRankingConfig ? "Saving…" : "Save"}
                    </button>
                  </div>
                  <p className="border-l-2 border-primary/20 pl-3 text-[10px] leading-relaxed text-muted-foreground">
                    Drag patterns between severity buckets or type to add new ones. Strong = heavily downranked, Adjacent = softened, Hybrid = mild penalty.
                  </p>
                  <div className="grid gap-3 xl:grid-cols-3">
                    <DraggableTagList
                      listId="strong"
                      title="Strong"
                      tone="text-destructive"
                      items={editPenaltyStrong}
                      onChange={setEditPenaltyStrong}
                      onReceiveDrop={(item, src) => {
                        if (src === "adjacent") setEditPenaltyAdjacent((p) => p.filter((x) => x !== item));
                        if (src === "hybrid") setEditPenaltyHybrid((p) => p.filter((x) => x !== item));
                      }}
                      emptyLabel="No strong penalties."
                      placeholder="e.g. support, tester"
                    />
                    <DraggableTagList
                      listId="adjacent"
                      title="Adjacent"
                      tone="text-[var(--terminal-yellow)]"
                      items={editPenaltyAdjacent}
                      onChange={setEditPenaltyAdjacent}
                      onReceiveDrop={(item, src) => {
                        if (src === "strong") setEditPenaltyStrong((p) => p.filter((x) => x !== item));
                        if (src === "hybrid") setEditPenaltyHybrid((p) => p.filter((x) => x !== item));
                      }}
                      emptyLabel="No adjacent penalties."
                      placeholder="e.g. devops, architect"
                    />
                    <DraggableTagList
                      listId="hybrid"
                      title="Hybrid"
                      tone="text-primary"
                      items={editPenaltyHybrid}
                      onChange={setEditPenaltyHybrid}
                      onReceiveDrop={(item, src) => {
                        if (src === "strong") setEditPenaltyStrong((p) => p.filter((x) => x !== item));
                        if (src === "adjacent") setEditPenaltyAdjacent((p) => p.filter((x) => x !== item));
                      }}
                      emptyLabel="No hybrid penalties."
                      placeholder="e.g. backend, java"
                    />
                  </div>
                </div>

                <div className="stat-card card-hover space-y-5 border border-border bg-card p-5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Briefcase size={13} className="text-primary" />
                      <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Top Company Tiers</span>
                    </div>
                    <button
                      type="button"
                      onClick={saveRankingConfig}
                      disabled={savingRankingConfig}
                      className="flex items-center gap-1.5 px-3 py-1 text-[11px] border border-primary/30 text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
                    >
                      <Save size={10} />
                      {savingRankingConfig ? "Saving…" : "Save"}
                    </button>
                  </div>
                  <p className="border-l-2 border-primary/20 pl-3 text-[10px] leading-relaxed text-muted-foreground">
                    Drag companies between tiers or type to add. SS gets the strongest score boost (+60%), S gets +50%.
                  </p>
                  <div className="grid gap-3 xl:grid-cols-2">
                    <DraggableTagList
                      listId="tier_ss"
                      title="Tier SS"
                      tone="text-primary"
                      items={editTierSS}
                      onChange={setEditTierSS}
                      onReceiveDrop={(item) => setEditTierS((p) => p.filter((x) => x !== item))}
                      emptyLabel="No Tier SS companies."
                      placeholder="e.g. Atlassian, Google"
                    />
                    <DraggableTagList
                      listId="tier_s"
                      title="Tier S"
                      tone="text-[var(--terminal-green-bright)]"
                      items={editTierS}
                      onChange={setEditTierS}
                      onReceiveDrop={(item) => setEditTierSS((p) => p.filter((x) => x !== item))}
                      emptyLabel="No Tier S companies."
                      placeholder="e.g. Microsoft, Stripe"
                    />
                  </div>
                </div>
              </div>
            )}

            {activeSection === "recruiters" && (
              <div className="space-y-6">
                <div className="stat-card card-hover space-y-5 border border-border bg-card p-5">
                  <div className="flex items-center gap-2">
                    <Search size={13} className="text-primary" />
                    <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Recruiter Finder</span>
                  </div>

                  <p className="border-l-2 border-primary/20 pl-3 text-[11px] leading-relaxed text-muted-foreground">
                    Searches DuckDuckGo + OpenRouter web for LinkedIn recruiter profiles at a company. Found profiles are saved and appear as mail targets in the tracker.
                  </p>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div>
                      <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">Company</label>
                      <input
                        type="text"
                        value={findCompany}
                        onChange={(e) => setFindCompany(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && findRecruiters()}
                        placeholder="e.g. Adobe"
                        suppressHydrationWarning
                        className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-[10px] uppercase tracking-wider text-muted-foreground">Domain (optional)</label>
                      <input
                        type="text"
                        value={findDomain}
                        onChange={(e) => setFindDomain(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && findRecruiters()}
                        placeholder="e.g. adobe.com"
                        suppressHydrationWarning
                        className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                      />
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={findRecruiters}
                    disabled={finding || !findCompany.trim()}
                    className="inline-flex items-center gap-2 border border-primary/30 px-4 py-2 text-[11px] uppercase tracking-wider text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
                  >
                    {finding ? (
                      <>
                        <RefreshCw size={10} className="animate-spin" />
                        Searching...
                      </>
                    ) : (
                      <>
                        <Search size={10} />
                        Find Recruiters
                      </>
                    )}
                  </button>

                  {foundRecruiters.length > 0 && (
                    <div className="space-y-1.5 border-t border-border pt-4">
                      <div className="text-[11px] uppercase tracking-wider text-primary">
                        Found {foundRecruiters.length} result(s)
                      </div>
                      {foundRecruiters.map((recruiter, index) => (
                        <div
                          key={`${recruiter.linkedin_url}-${index}`}
                          className="mx-[-0.5rem] flex items-center gap-3 border-b border-border/30 px-2 py-2 text-xs transition-colors last:border-0 hover:bg-primary/5"
                        >
                          <span className="w-40 truncate text-foreground">{recruiter.name ?? "—"}</span>
                          <span className="flex-1 truncate text-muted-foreground">{recruiter.email ?? "no email"}</span>
                          <span className="border border-primary/20 px-1.5 py-0.5 text-[10px] text-primary/70">{recruiter.confidence}</span>
                          <a
                            href={recruiter.linkedin_url}
                            target="_blank"
                            rel="noreferrer"
                            className="shrink-0 text-[10px] text-[#0a66c2] transition-colors hover:text-primary"
                          >
                            LinkedIn ↗
                          </a>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="stat-card card-hover space-y-4 border border-border bg-card p-5">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex items-center gap-2">
                      <Briefcase size={13} className="text-primary" />
                      <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Recruiter Database</span>
                      <span className="tabular-nums text-[10px] text-primary">{allRecruiters.length}</span>
                    </div>
                    <div className="relative">
                      <Search size={10} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
                      <input
                        type="text"
                        value={recruiterCompanyFilter}
                        onChange={(e) => setRecruiterCompanyFilter(e.target.value)}
                        placeholder="Filter company..."
                        suppressHydrationWarning
                        className="w-44 border border-border bg-input py-1.5 pl-6 pr-2 text-[11px] text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
                      />
                    </div>
                  </div>

                  {filteredRecruiters.length === 0 ? (
                    <div className="py-4 text-center text-[11px] text-muted-foreground">
                      {allRecruiters.length === 0 ? "No recruiters found. Use the finder above to discover recruiters." : "No matches for filter."}
                    </div>
                  ) : (
                    <div className="max-h-72 space-y-0.5 overflow-y-auto">
                      {filteredRecruiters.map((recruiter) => (
                        <div
                          key={recruiter.id}
                          className="mx-[-0.25rem] flex items-center gap-3 border-b border-border/20 px-1 py-2 text-[11px] transition-colors last:border-0 hover:bg-primary/5"
                        >
                          <span className="w-28 shrink-0 truncate font-medium text-primary/70">{recruiter.company}</span>
                          <span className="w-32 shrink-0 truncate text-foreground">{recruiter.name ?? "—"}</span>
                          <span className="flex-1 truncate text-muted-foreground">{recruiter.email ?? "—"}</span>
                          {recruiter.linkedin_url && (
                            <a
                              href={recruiter.linkedin_url}
                              target="_blank"
                              rel="noreferrer"
                              className="shrink-0 text-[#0a66c2] transition-colors hover:text-primary"
                            >
                              ↗
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {activeSection === "developer" && isDev && (
              <div className="space-y-4">
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

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { swr } from "@/lib/cache";
import { loadProfileOptions, PROFILE_OPTIONS_FALLBACK } from "@/lib/profile-options";
import { makeQueuedRun, upsertRunCaches } from "@/lib/run-cache";
import type { Profile, Run } from "@/types";
import { useToast } from "@/components/toast";
import RunProgress from "@/components/run-progress";
import { TagInput } from "@/components/tag-input";
import { Search, RefreshCw, User, Target, Briefcase, Shield, Save, CheckCircle, Info, Play } from "lucide-react";

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

function serializeSettingsSnapshot(input: {
  targetRoles: string[];
  locations: string[];
  customQueries: string[];
  targetLpa: string;
  minYoe: string;
  maxYoe: string;
  scraperHoursOld: string;
  scraperMaxTerms: string;
}) {
  return JSON.stringify(input);
}

export default function SettingsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [saving, setSaving] = useState(false);
  const [triggeringDeepScan, setTriggeringDeepScan] = useState(false);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [run, setRun] = useState<Run | null>(null);

  const [targetRoles, setTargetRoles] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [roleOptions, setRoleOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.role_options);
  const [locationOptions, setLocationOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.location_options);
  const [customQueries, setCustomQueries] = useState<string[]>([]);
  const [targetLpa, setTargetLpa] = useState("");
  const [minYoe, setMinYoe] = useState("");
  const [maxYoe, setMaxYoe] = useState("");
  const [scraperHoursOld, setScraperHoursOld] = useState("");
  const [scraperMaxTerms, setScraperMaxTerms] = useState("");

  const loaded = useRef(false);
  const snapshotRef = useRef("");

  const [findCompany, setFindCompany] = useState("");
  const [findDomain, setFindDomain] = useState("");
  const [finding, setFinding] = useState(false);
  const [foundRecruiters, setFoundRecruiters] = useState<FoundRecruiter[]>([]);
  const [allRecruiters, setAllRecruiters] = useState<RecruiterRow[]>([]);
  const [recruiterCompanyFilter, setRecruiterCompanyFilter] = useState("");

  const load = useCallback(async () => {
    if (!token) return;
    const p = await api.profile.get(token);
    setProfile(p);
    setTargetRoles(p.target_roles ?? []);
    setLocations(p.preferred_locations ?? []);
    setCustomQueries(p.custom_search_queries ?? []);
    setTargetLpa(p.target_lpa != null ? String(p.target_lpa) : "");
    setMinYoe(p.min_yoe != null ? String(p.min_yoe) : "");
    setMaxYoe(p.max_yoe != null ? String(p.max_yoe) : "");
    setScraperHoursOld(p.scraper_hours_old != null ? String(p.scraper_hours_old) : "");
    setScraperMaxTerms(p.scraper_max_terms != null ? String(p.scraper_max_terms) : "");
    snapshotRef.current = serializeSettingsSnapshot({
      targetRoles: p.target_roles ?? [],
      locations: p.preferred_locations ?? [],
      customQueries: p.custom_search_queries ?? [],
      targetLpa: p.target_lpa != null ? String(p.target_lpa) : "",
      minYoe: p.min_yoe != null ? String(p.min_yoe) : "",
      maxYoe: p.max_yoe != null ? String(p.max_yoe) : "",
      scraperHoursOld: p.scraper_hours_old != null ? String(p.scraper_hours_old) : "",
      scraperMaxTerms: p.scraper_max_terms != null ? String(p.scraper_max_terms) : "",
    });
    setDirty(false);
    loaded.current = true;
  }, [token]);

  const loadRecruiters = useCallback(async () => {
    if (!token) return;
    const recs = await api.recruiters.list(token);
    setAllRecruiters(recs);
  }, [token]);

  useEffect(() => {
    load();
    loadRecruiters();
  }, [load, loadRecruiters]);

  useEffect(() => {
    if (!token) return;
    loadProfileOptions(token).then((options) => {
      setRoleOptions(options.role_options);
      setLocationOptions(options.location_options);
    });
  }, [token]);

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
      }),
    [targetRoles, locations, customQueries, targetLpa, minYoe, maxYoe, scraperHoursOld, scraperMaxTerms]
  );

  useEffect(() => {
    if (!loaded.current) return;
    setDirty(currentSnapshot !== snapshotRef.current);
  }, [currentSnapshot]);

  async function save() {
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
      });
      snapshotRef.current = currentSnapshot;
      toast("Settings saved", "success");
      setSaved(true);
      setDirty(false);
      setTimeout(() => setSaved(false), 2000);
      return true;
    } catch {
      toast("Save failed", "error");
      return false;
    } finally {
      setSaving(false);
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
    if (!findCompany.trim()) return;
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
      loadRecruiters();
    } catch {
      toast("Recruiter search failed", "error");
    } finally {
      setFinding(false);
    }
  }

  const filteredRecruiters = recruiterCompanyFilter
    ? allRecruiters.filter((r) =>
        r.company?.toLowerCase().includes(recruiterCompanyFilter.toLowerCase())
      )
    : allRecruiters;

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-3xl mx-auto px-6 py-8 space-y-7">

        {/* Header */}
        <div className="space-y-1">
          <div className="section-label">settings</div>
          <h1 className="text-xl font-bold text-foreground tracking-tight">Configuration</h1>
        </div>

        {/* Profile */}
        <div className="stat-card card-hover border border-border bg-card p-5 space-y-5">
          <div className="flex items-center gap-2">
            <User size={13} className="text-primary" />
            <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Profile</span>
          </div>

          {profile && (
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 border border-primary/30 bg-primary/5 flex items-center justify-center shrink-0">
                <span className="text-primary text-sm font-bold">{profile.email[0].toUpperCase()}</span>
              </div>
              <div>
                <div className="text-xs text-foreground font-medium">{profile.email}</div>
                <div className="flex items-center gap-1.5 mt-0.5">
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

          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Target LPA", value: targetLpa, set: setTargetLpa, placeholder: "60", suffix: "L" },
              { label: "Min YOE", value: minYoe, set: setMinYoe, placeholder: "3", suffix: "yr" },
              { label: "Max YOE", value: maxYoe, set: setMaxYoe, placeholder: "12", suffix: "yr" },
            ].map(({ label, value, set, placeholder, suffix }) => (
              <div key={label}>
                <label className="block text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">
                  {label}
                </label>
                <div className="relative">
                  <input
                    type="number"
                    value={value}
                    onChange={(e) => set(e.target.value)}
                    placeholder={placeholder}
                    className="w-full text-xs bg-input border border-border text-foreground px-3 py-2 focus:border-primary focus:outline-none placeholder:text-muted-foreground/40 transition-colors"
                  />
                  <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">{suffix}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

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

        {/* Search Preferences */}
        <div className="stat-card card-hover border border-border bg-card p-5 space-y-5">
          <div className="flex items-center gap-2">
            <Target size={13} className="text-primary" />
            <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Search Preferences</span>
          </div>

          <TagInput
            label="Target Roles"
            value={targetRoles}
            onChange={setTargetRoles}
            placeholder="Add role, press Enter..."
            suggestions={roleOptions}
          />

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

        {/* Scraping Config */}
        <div className="stat-card card-hover border border-border bg-card p-5 space-y-5">
          <div className="flex items-center gap-2">
            <RefreshCw size={13} className="text-primary" />
            <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Scraping Config</span>
          </div>
          <p className="text-[10px] text-muted-foreground leading-relaxed border-l-2 border-primary/20 pl-3">
            Quick refresh uses Indeed only with 1 title and a 24h lookback. Full background runs use all roles and sources.
            Raise the lookback here if you want the scraper to search further back in time.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">
                Full Run Lookback (hours)
              </label>
              <div className="relative">
                <input
                  type="number"
                  value={scraperHoursOld}
                  onChange={(e) => setScraperHoursOld(e.target.value)}
                  placeholder="168"
                  className="w-full text-xs bg-input border border-border text-foreground px-3 py-2 focus:border-primary focus:outline-none placeholder:text-muted-foreground/40 transition-colors"
                />
                <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground">hrs</span>
              </div>
              <div className="mt-1 flex items-start gap-1.5 text-[10px] text-muted-foreground/80 leading-relaxed">
                <Info size={10} className="mt-0.5 shrink-0 text-primary" />
                <span>Example: 168 = 7 days, 720 = 30 days. Higher values widen future scans.</span>
              </div>
            </div>
            <div>
              <label className="block text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">
                Full Run Max Titles
              </label>
              <input
                type="number"
                value={scraperMaxTerms}
                onChange={(e) => setScraperMaxTerms(e.target.value)}
                placeholder="all"
                className="w-full text-xs bg-input border border-border text-foreground px-3 py-2 focus:border-primary focus:outline-none placeholder:text-muted-foreground/40 transition-colors"
              />
            </div>
          </div>
          <div className="flex flex-col gap-3 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="text-[11px] text-muted-foreground leading-relaxed">
              Longer-duration and multi-title scans are only launched from here. The button below uses the saved lookback and title settings on this page.
            </div>
            <button
              onClick={triggerDeepScan}
              disabled={triggeringDeepScan || saving}
              className="inline-flex items-center justify-center gap-2 border border-primary/50 px-4 py-2 text-[11px] uppercase tracking-wider text-primary transition-colors hover:bg-primary/10 disabled:opacity-50"
            >
              {triggeringDeepScan ? (
                <>
                  <RefreshCw size={10} className="animate-spin" />
                  Queuing deep scan...
                </>
              ) : (
                <>
                  <Play size={10} />
                  Run deep scan
                </>
              )}
            </button>
          </div>
        </div>

        {/* Save button */}
        <div className="flex items-center justify-end gap-3">
          <span className="text-[10px] text-muted-foreground">
            {dirty ? "Unsaved changes" : "Changes saved"}
          </span>
          <button
            onClick={save}
            disabled={saving || triggeringDeepScan || !dirty}
            className="flex items-center gap-2 text-[11px] border px-5 py-2 uppercase tracking-wider transition-all duration-150 disabled:opacity-50"
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

        {/* Recruiter Finder */}
        <div>
          <div className="section-label mb-3">recruiter tools</div>
          <div className="stat-card card-hover border border-border bg-card p-5 space-y-5">
            <div className="flex items-center gap-2">
              <Search size={13} className="text-primary" />
              <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">Recruiter Finder</span>
            </div>

            <p className="text-[11px] text-muted-foreground leading-relaxed border-l-2 border-primary/20 pl-3">
              Searches DuckDuckGo + OpenRouter web for LinkedIn recruiter profiles at a company.
              Found profiles are saved and appear as mail targets in the tracker.
            </p>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">
                  Company
                </label>
                <input
                  type="text"
                  value={findCompany}
                  onChange={(e) => setFindCompany(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && findRecruiters()}
                  placeholder="e.g. Adobe"
                  className="w-full text-xs bg-input border border-border text-foreground px-3 py-2 focus:border-primary focus:outline-none placeholder:text-muted-foreground/40 transition-colors"
                />
              </div>
              <div>
                <label className="block text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">
                  Domain (optional)
                </label>
                <input
                  type="text"
                  value={findDomain}
                  onChange={(e) => setFindDomain(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && findRecruiters()}
                  placeholder="e.g. adobe.com"
                  className="w-full text-xs bg-input border border-border text-foreground px-3 py-2 focus:border-primary focus:outline-none placeholder:text-muted-foreground/40 transition-colors"
                />
              </div>
            </div>

            <button
              onClick={findRecruiters}
              disabled={finding || !findCompany.trim()}
              className="flex items-center gap-2 text-[11px] text-primary border border-primary/30 px-4 py-2 hover:bg-primary/10 transition-colors uppercase tracking-wider disabled:opacity-50"
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
                <div className="text-[11px] text-primary uppercase tracking-wider">
                  Found {foundRecruiters.length} result(s)
                </div>
                {foundRecruiters.map((r, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs py-2 border-b border-border/30 last:border-0 hover:bg-primary/5 transition-colors px-2 -mx-2">
                    <span className="text-foreground w-40 truncate">{r.name ?? "—"}</span>
                    <span className="text-muted-foreground truncate flex-1">{r.email ?? "no email"}</span>
                    <span className="text-[10px] px-1.5 py-0.5 border border-primary/20 text-primary/70">{r.confidence}</span>
                    {r.linkedin_url && (
                      <a href={r.linkedin_url} target="_blank" rel="noreferrer" className="text-[#0a66c2] hover:text-primary transition-colors text-[10px] shrink-0">
                        LinkedIn ↗
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Recruiter Database */}
        <div className="stat-card card-hover border border-border bg-card p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Briefcase size={13} className="text-primary" />
              <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">
                Recruiter Database
              </span>
              <span className="text-[10px] text-primary tabular-nums">{allRecruiters.length}</span>
            </div>
            <div className="relative">
              <Search size={10} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                value={recruiterCompanyFilter}
                onChange={(e) => setRecruiterCompanyFilter(e.target.value)}
                placeholder="Filter company..."
                className="text-[11px] bg-input border border-border text-foreground pl-6 pr-2 py-1.5 focus:border-primary focus:outline-none placeholder:text-muted-foreground/40 w-44 transition-colors"
              />
            </div>
          </div>

          {filteredRecruiters.length === 0 ? (
            <div className="text-[11px] text-muted-foreground py-4 text-center">
              {allRecruiters.length === 0 ? "No recruiters found. Use the finder above to discover recruiters." : "No matches for filter."}
            </div>
          ) : (
            <div className="space-y-0.5 max-h-72 overflow-y-auto">
              {filteredRecruiters.map((r) => (
                <div key={r.id} className="flex items-center gap-3 text-[11px] py-2 border-b border-border/20 last:border-0 hover:bg-primary/5 transition-colors px-1 -mx-1">
                  <span className="text-primary/70 w-28 shrink-0 truncate font-medium">{r.company}</span>
                  <span className="text-foreground w-32 shrink-0 truncate">{r.name ?? "—"}</span>
                  <span className="text-muted-foreground truncate flex-1">{r.email ?? "—"}</span>
                  {r.linkedin_url && (
                    <a href={r.linkedin_url} target="_blank" rel="noreferrer" className="text-[#0a66c2] hover:text-primary transition-colors shrink-0">
                      ↗
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

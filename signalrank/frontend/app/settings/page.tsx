"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import type { Profile } from "@/types";
import { useToast } from "@/components/toast";
import { TagInput } from "@/components/tag-input";
import { Search, RefreshCw, User, Target, MapPin, Briefcase, Code } from "lucide-react";

const ROLE_SUGGESTIONS = [
  "ML Engineer", "Senior ML Engineer", "Staff ML Engineer",
  "AI Engineer", "Senior AI Engineer",
  "MLOps Engineer", "LLMOps Engineer",
  "Platform Engineer", "Senior Platform Engineer", "Staff Platform Engineer",
  "Backend Engineer", "Senior Backend Engineer",
  "Data Scientist", "Senior Data Scientist",
  "AI Platform Engineer", "Agentic Systems Engineer",
];

const LOCATION_SUGGESTIONS = [
  "India", "Remote", "Bangalore", "Pune", "Hyderabad", "Mumbai",
  "Chennai", "Delhi", "Noida", "Gurgaon",
  "United States", "United Kingdom", "Germany", "Netherlands",
];

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

export default function SettingsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [saving, setSaving] = useState(false);

  // Editable fields
  const [targetRoles, setTargetRoles] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [customQueries, setCustomQueries] = useState<string[]>([]);
  const [targetLpa, setTargetLpa] = useState("");
  const [minYoe, setMinYoe] = useState("");
  const [maxYoe, setMaxYoe] = useState("");

  // Recruiter finder
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

  async function save() {
    setSaving(true);
    try {
      await api.profile.patch(token, {
        target_roles: targetRoles,
        preferred_locations: locations,
        custom_search_queries: customQueries,
        target_lpa: targetLpa ? Number(targetLpa) : null,
        min_yoe: minYoe ? Number(minYoe) : null,
        max_yoe: maxYoe ? Number(maxYoe) : null,
      });
      toast("Settings saved", "success");
    } catch {
      toast("Save failed", "error");
    } finally {
      setSaving(false);
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

  const uniqueCompanies = [...new Set(allRecruiters.map((r) => r.company).filter(Boolean))].sort();

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
        <h1 className="text-lg font-mono font-semibold text-primary uppercase tracking-widest">
          Settings
        </h1>

        {/* Profile section */}
        <section className="border border-border p-5 space-y-5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wider font-mono">
            <User size={12} />
            Profile
          </div>

          {profile && (
            <div className="text-xs text-secondary-foreground font-mono space-y-1">
              <div>{profile.email}</div>
              <div className="text-muted-foreground">
                {profile.onboarding_complete ? "Onboarding complete" : "Onboarding incomplete"}
              </div>
            </div>
          )}

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-[11px] text-muted-foreground uppercase tracking-wider mb-1">
                Target LPA
              </label>
              <input
                type="number"
                value={targetLpa}
                onChange={(e) => setTargetLpa(e.target.value)}
                placeholder="60"
                className="w-full text-xs bg-transparent border border-border text-foreground px-2 py-1.5 focus:border-primary focus:outline-none placeholder:text-border"
              />
            </div>
            <div>
              <label className="block text-[11px] text-muted-foreground uppercase tracking-wider mb-1">
                Min YOE
              </label>
              <input
                type="number"
                value={minYoe}
                onChange={(e) => setMinYoe(e.target.value)}
                placeholder="5"
                className="w-full text-xs bg-transparent border border-border text-foreground px-2 py-1.5 focus:border-primary focus:outline-none placeholder:text-border"
              />
            </div>
            <div>
              <label className="block text-[11px] text-muted-foreground uppercase tracking-wider mb-1">
                Max YOE
              </label>
              <input
                type="number"
                value={maxYoe}
                onChange={(e) => setMaxYoe(e.target.value)}
                placeholder="12"
                className="w-full text-xs bg-transparent border border-border text-foreground px-2 py-1.5 focus:border-primary focus:outline-none placeholder:text-border"
              />
            </div>
          </div>
        </section>

        {/* Search preferences */}
        <section className="border border-border p-5 space-y-5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wider font-mono">
            <Target size={12} />
            Search Preferences
          </div>

          <TagInput
            label="Target Roles"
            value={targetRoles}
            onChange={setTargetRoles}
            placeholder="Add role, press Enter..."
            suggestions={ROLE_SUGGESTIONS}
          />

          <TagInput
            label="Preferred Locations"
            value={locations}
            onChange={setLocations}
            placeholder="Add location, press Enter..."
            suggestions={LOCATION_SUGGESTIONS}
          />

          <TagInput
            label="Custom Search Queries"
            value={customQueries}
            onChange={setCustomQueries}
            placeholder="e.g. 'LLM platform engineer Bangalore'"
          />
        </section>

        <div className="flex justify-end">
          <button
            onClick={save}
            disabled={saving}
            className="text-[11px] text-primary border border-primary/30 px-4 py-1.5 hover:bg-primary/10 transition-colors uppercase tracking-wider disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>

        {/* Recruiter Finder */}
        <section className="border border-border p-5 space-y-5">
          <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wider font-mono">
            <Search size={12} />
            Recruiter Finder
          </div>

          <p className="text-[11px] text-muted-foreground leading-relaxed">
            Searches DuckDuckGo + OpenRouter web for LinkedIn recruiter profiles at a company.
            Found profiles are saved to your recruiter database and appear as mail targets in the tracker.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] text-muted-foreground uppercase tracking-wider mb-1">
                Company
              </label>
              <input
                type="text"
                value={findCompany}
                onChange={(e) => setFindCompany(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && findRecruiters()}
                placeholder="e.g. Adobe"
                className="w-full text-xs bg-transparent border border-border text-foreground px-2 py-1.5 focus:border-primary focus:outline-none placeholder:text-border"
              />
            </div>
            <div>
              <label className="block text-[11px] text-muted-foreground uppercase tracking-wider mb-1">
                Domain (optional)
              </label>
              <input
                type="text"
                value={findDomain}
                onChange={(e) => setFindDomain(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && findRecruiters()}
                placeholder="e.g. adobe.com"
                className="w-full text-xs bg-transparent border border-border text-foreground px-2 py-1.5 focus:border-primary focus:outline-none placeholder:text-border"
              />
            </div>
          </div>

          <button
            onClick={findRecruiters}
            disabled={finding || !findCompany.trim()}
            className="flex items-center gap-2 text-[11px] text-primary border border-primary/30 px-3 py-1.5 hover:bg-primary/10 transition-colors uppercase tracking-wider disabled:opacity-50"
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
            <div className="space-y-1.5">
              <div className="text-[11px] text-muted-foreground uppercase tracking-wider">
                Found {foundRecruiters.length} result(s)
              </div>
              {foundRecruiters.map((r, i) => (
                <div key={i} className="flex items-center gap-3 text-xs py-1.5 border-b border-border/50 last:border-0">
                  <span className="text-secondary-foreground font-mono w-40 truncate">{r.name ?? "—"}</span>
                  <span className="text-muted-foreground truncate flex-1">{r.email ?? "no email"}</span>
                  {r.linkedin_url && (
                    <a href={r.linkedin_url} target="_blank" rel="noreferrer" className="text-[#0a66c2] hover:text-primary transition-colors text-[10px] shrink-0">
                      LinkedIn
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Recruiter database */}
        <section className="border border-border p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-muted-foreground uppercase tracking-wider font-mono">
              <Briefcase size={12} />
              Recruiter Database ({allRecruiters.length})
            </div>
            <input
              type="text"
              value={recruiterCompanyFilter}
              onChange={(e) => setRecruiterCompanyFilter(e.target.value)}
              placeholder="Filter by company..."
              className="text-[11px] bg-transparent border border-border text-foreground px-2 py-1 focus:border-primary focus:outline-none placeholder:text-border w-40"
            />
          </div>

          {filteredRecruiters.length === 0 ? (
            <div className="text-[11px] text-muted-foreground py-2">No recruiters found.</div>
          ) : (
            <div className="space-y-0.5 max-h-72 overflow-y-auto">
              {filteredRecruiters.map((r) => (
                <div key={r.id} className="flex items-center gap-3 text-[11px] py-1.5 border-b border-border/30 last:border-0">
                  <span className="text-muted-foreground w-28 shrink-0 truncate font-mono">{r.company}</span>
                  <span className="text-secondary-foreground w-32 shrink-0 truncate">{r.name ?? "—"}</span>
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
        </section>
      </div>
    </div>
  );
}

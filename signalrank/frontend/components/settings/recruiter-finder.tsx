"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Briefcase, RefreshCw, Search } from "lucide-react";

import { useToast } from "@/components/toast";
import { api } from "@/lib/api";

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

interface RecruiterFinderProps {
  token: string;
}

export function RecruiterFinder({ token }: RecruiterFinderProps) {
  const { toast } = useToast();

  const [findCompany, setFindCompany] = useState("");
  const [findDomain, setFindDomain] = useState("");
  const [finding, setFinding] = useState(false);
  const [foundRecruiters, setFoundRecruiters] = useState<FoundRecruiter[]>([]);
  const [allRecruiters, setAllRecruiters] = useState<RecruiterRow[]>([]);
  const [recruiterCompanyFilter, setRecruiterCompanyFilter] = useState("");

  const loadRecruiters = useCallback(async () => {
    if (!token) return;
    const recs = await api.recruiters.list(token);
    setAllRecruiters(recs);
  }, [token]);

  useEffect(() => {
    let cancelled = false;
    loadRecruiters().catch(() => {
      if (!cancelled) toast("Failed to load recruiters", "error");
    });
    return () => { cancelled = true; };
  }, [loadRecruiters, toast]);

  const filteredRecruiters = useMemo(
    () =>
      recruiterCompanyFilter
        ? allRecruiters.filter((r) => r.company?.toLowerCase().includes(recruiterCompanyFilter.toLowerCase()))
        : allRecruiters,
    [allRecruiters, recruiterCompanyFilter],
  );

  async function findRecruitersAction() {
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

  return (
    <div className="tab-enter space-y-6">
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
              onKeyDown={(e) => e.key === "Enter" && findRecruitersAction()}
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
              onKeyDown={(e) => e.key === "Enter" && findRecruitersAction()}
              placeholder="e.g. adobe.com"
              suppressHydrationWarning
              className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
            />
          </div>
        </div>

        <button
          type="button"
          onClick={findRecruitersAction}
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
  );
}

"use client";

import { useState } from "react";
import { Briefcase, Info, Play, RefreshCw, Save, Target } from "lucide-react";

import { TagInput } from "@/components/tag-input";
import { DraggableTagList } from "@/components/draggable-tag-list";
import { useToast } from "@/components/toast";
import { api } from "@/lib/api";
import { formatPenaltyPattern } from "@/lib/formatting";

interface TitlePenaltyRules {
  strong: string[];
  adjacent: string[];
  hybrid: string[];
}

interface SearchConfigProps {
  token: string;
  targetRoles: string[];
  setTargetRoles: (v: string[]) => void;
  locations: string[];
  setLocations: (v: string[]) => void;
  customQueries: string[];
  setCustomQueries: (v: string[]) => void;
  roleOptions: string[];
  locationOptions: string[];
  scraperHoursOld: string;
  setScraperHoursOld: (v: string) => void;
  scraperMaxTerms: string;
  setScraperMaxTerms: (v: string) => void;
  titlePenaltyRules: TitlePenaltyRules;
  initialTierSS: string[];
  initialTierS: string[];
  initialPenaltyStrong: string[];
  initialPenaltyAdjacent: string[];
  initialPenaltyHybrid: string[];
  triggerDeepScan: () => void;
  triggeringDeepScan: boolean;
  saving: boolean;
}

export function SearchConfig({
  token,
  targetRoles,
  setTargetRoles,
  locations,
  setLocations,
  customQueries,
  setCustomQueries,
  roleOptions,
  locationOptions,
  scraperHoursOld,
  setScraperHoursOld,
  scraperMaxTerms,
  setScraperMaxTerms,
  titlePenaltyRules,
  initialTierSS,
  initialTierS,
  initialPenaltyStrong,
  initialPenaltyAdjacent,
  initialPenaltyHybrid,
  triggerDeepScan,
  triggeringDeepScan,
  saving,
}: SearchConfigProps) {
  const { toast } = useToast();

  const [editTierSS, setEditTierSS] = useState<string[]>(initialTierSS);
  const [editTierS, setEditTierS] = useState<string[]>(initialTierS);
  const [editPenaltyStrong, setEditPenaltyStrong] = useState<string[]>(initialPenaltyStrong);
  const [editPenaltyAdjacent, setEditPenaltyAdjacent] = useState<string[]>(initialPenaltyAdjacent);
  const [editPenaltyHybrid, setEditPenaltyHybrid] = useState<string[]>(initialPenaltyHybrid);
  const [savingRankingConfig, setSavingRankingConfig] = useState(false);

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

  return (
    <div className="tab-enter space-y-6">
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
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setEditPenaltyStrong(titlePenaltyRules.strong.map(formatPenaltyPattern));
                setEditPenaltyAdjacent(titlePenaltyRules.adjacent.map(formatPenaltyPattern));
                setEditPenaltyHybrid(titlePenaltyRules.hybrid.map(formatPenaltyPattern));
              }}
              className="flex items-center gap-1.5 px-3 py-1 text-[11px] border border-muted-foreground/30 text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
              title="Reset to auto-generated penalties based on your profile"
            >
              <RefreshCw size={10} />
              Reset to auto
            </button>
            <button
              type="button"
              onClick={saveRankingConfig}
              disabled={savingRankingConfig}
              className="flex items-center gap-1.5 px-3 py-1 text-[11px] border border-primary/30 text-primary hover:bg-primary/10 transition-colors disabled:opacity-50"
            >
              <Save size={10} />
              {savingRankingConfig ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
        <p className="border-l-2 border-primary/20 pl-3 text-[10px] leading-relaxed text-muted-foreground">
          Auto-grouped from your profile archetype. Drag patterns between severity buckets, type to add, or reset to auto.
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
            {savingRankingConfig ? "Saving..." : "Save"}
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
  );
}

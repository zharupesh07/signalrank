"use client";

import { useEffect, useState } from "react";
import { X, Sun, Moon } from "lucide-react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { loadProfileOptions, PROFILE_OPTIONS_FALLBACK } from "@/lib/profile-options";
import { TagInput } from "@/components/tag-input";
import { useTheme } from "@/components/theme-provider";
import { useToast } from "@/components/toast";
import type { Profile } from "@/types";

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

const inputCls =
  "bg-[var(--bg-input)] border border-[var(--border)] rounded px-3 py-1.5 text-sm text-[var(--fg)] w-full outline-none focus:border-[var(--accent)]";

export function SettingsPanel({ isOpen, onClose }: SettingsPanelProps) {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { theme, toggleTheme } = useTheme();
  const { toast } = useToast();

  const [targetRoles, setTargetRoles] = useState<string[]>([]);
  const [preferredLocations, setPreferredLocations] = useState<string[]>([]);
  const [roleOptions, setRoleOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.role_options);
  const [locationOptions, setLocationOptions] = useState<string[]>(PROFILE_OPTIONS_FALLBACK.location_options);
  const [customSearchQueries, setCustomSearchQueries] = useState<string[]>([]);
  const [minYoe, setMinYoe] = useState<string>("");
  const [maxYoe, setMaxYoe] = useState<string>("");
  const [targetLpa, setTargetLpa] = useState<string>("");
  const [titleBlocklist, setTitleBlocklist] = useState<string[]>([]);

  useEffect(() => {
    if (!isOpen || !token) return;
    api.profile.get(token).then((p: Profile) => {
      setTargetRoles(p.target_roles ?? []);
      setPreferredLocations(p.preferred_locations ?? []);
      setCustomSearchQueries(p.custom_search_queries ?? []);
      setMinYoe(p.min_yoe != null ? String(p.min_yoe) : "");
      setMaxYoe(p.max_yoe != null ? String(p.max_yoe) : "");
      setTargetLpa(p.target_lpa != null ? String(p.target_lpa) : "");
      const blocklist = (p.config_overrides?.title_blocklist as string[] | undefined) ?? [];
      setTitleBlocklist(blocklist);
    }).catch(() => null);
  }, [isOpen, token]);

  useEffect(() => {
    if (!isOpen || !token) return;
    loadProfileOptions(token).then((options) => {
      setRoleOptions(options.role_options);
      setLocationOptions(options.location_options);
    });
  }, [isOpen, token]);

  async function save() {
    if (!token) return;
    const configOverrides: Record<string, unknown> = { title_blocklist: titleBlocklist };
    await api.profile.patch(token, {
      target_roles: targetRoles,
      preferred_locations: preferredLocations,
      custom_search_queries: customSearchQueries,
      min_yoe: minYoe !== "" ? Number(minYoe) : null,
      max_yoe: maxYoe !== "" ? Number(maxYoe) : null,
      target_lpa: targetLpa !== "" ? Number(targetLpa) : null,
      config_overrides: configOverrides,
    });
    toast("Settings saved", "success");
  }

  async function handleClose() {
    await save();
    onClose();
  }

  return (
    <>
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
          onClick={handleClose}
        />
      )}

      <div
        className={`fixed top-0 right-0 z-50 h-full w-80 bg-[var(--bg-card)] border-l border-[var(--border)] overflow-y-auto flex flex-col transition-transform duration-300 ${
          isOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
          <span className="text-sm font-semibold text-[var(--fg-heading)]">Settings</span>
          <button
            onClick={handleClose}
            className="text-[var(--fg-muted)] hover:text-[var(--fg)] transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 px-4 py-4 flex flex-col gap-6">
          {/* Appearance */}
          <section>
            <p className="text-xs font-semibold text-[var(--fg-muted)] uppercase tracking-wider mb-3">
              Appearance
            </p>
            <div className="flex items-center justify-between">
              <span className="text-sm text-[var(--fg)]">Theme</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--fg-muted)]">
                  {theme === "dark" ? "Dark" : "Light"}
                </span>
                <button
                  onClick={toggleTheme}
                  className="p-1.5 rounded bg-[var(--bg-subtle)] border border-[var(--border)] text-[var(--fg-muted)] hover:text-[var(--fg)] transition-colors"
                >
                  {theme === "dark" ? <Sun size={14} /> : <Moon size={14} />}
                </button>
              </div>
            </div>
          </section>

          <div className="border-t border-[var(--border-muted)]" />

          {/* Search Config */}
          <section>
            <p className="text-xs font-semibold text-[var(--fg-muted)] uppercase tracking-wider mb-3">
              Search Config
            </p>
            <div className="flex flex-col gap-3">
              <TagInput
                label="Target roles"
                value={targetRoles}
                onChange={setTargetRoles}
                placeholder="Add role…"
                suggestions={roleOptions}
              />
              <TagInput
                label="Preferred locations"
                value={preferredLocations}
                onChange={setPreferredLocations}
                placeholder="Add location…"
                suggestions={locationOptions}
              />
              <TagInput
                label="Custom search queries"
                value={customSearchQueries}
                onChange={setCustomSearchQueries}
                placeholder="Add query…"
              />
            </div>
          </section>

          <div className="border-t border-[var(--border-muted)]" />

          {/* Ranking Filters */}
          <section>
            <p className="text-xs font-semibold text-[var(--fg-muted)] uppercase tracking-wider mb-3">
              Ranking Filters
            </p>
            <div className="flex flex-col gap-3">
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="block text-xs text-[var(--fg-muted)] mb-1">Min YOE</label>
                  <input
                    type="number"
                    value={minYoe}
                    onChange={(e) => setMinYoe(e.target.value)}
                    placeholder="0"
                    className={inputCls}
                  />
                </div>
                <div className="flex-1">
                  <label className="block text-xs text-[var(--fg-muted)] mb-1">Max YOE</label>
                  <input
                    type="number"
                    value={maxYoe}
                    onChange={(e) => setMaxYoe(e.target.value)}
                    placeholder="20"
                    className={inputCls}
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs text-[var(--fg-muted)] mb-1">Target LPA</label>
                <input
                  type="number"
                  value={targetLpa}
                  onChange={(e) => setTargetLpa(e.target.value)}
                  placeholder="60"
                  className={inputCls}
                />
              </div>
              <TagInput
                label="Title blocklist"
                value={titleBlocklist}
                onChange={setTitleBlocklist}
                placeholder="Add title…"
                suggestions={["Intern", "Trainee", "Fresher", "Junior", "Associate", "Lead", "Manager", "Director", "VP", "Head", "Chief", "Principal", "Staff", "Consultant", "Freelance", "Part-time"]}
              />
            </div>
          </section>
        </div>

        <div className="px-4 py-3 border-t border-[var(--border)]">
          <button
            onClick={save}
            className="w-full py-2 rounded bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Save
          </button>
        </div>
      </div>
    </>
  );
}

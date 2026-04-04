"use client";

import { useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Eye,
  FileText,
  RefreshCw,
  Upload,
} from "lucide-react";

import { useToast } from "@/components/toast";
import { ResumePreviewSkeleton } from "@/components/skeleton";
import { api } from "@/lib/api";
import type { ResumeEditor as ResumeEditorType, ResumeEditorExperience } from "@/types";

type ResumeWorkspaceSection = "basics" | "summary" | "experience" | "projects" | "skills" | "certifications";

function looksLikeUrl(value: string) {
  const trimmed = value.trim();
  const lower = trimmed.toLowerCase();
  return (
    !trimmed ||
    trimmed.startsWith("http://") ||
    trimmed.startsWith("https://") ||
    trimmed.startsWith("www.") ||
    lower.includes("linkedin.com/") ||
    lower.includes("github.com/") ||
    /^[A-Za-z0-9._-]{2,}$/.test(trimmed) ||
    (trimmed.includes(".") && !trimmed.includes(" ") && !trimmed.includes("@") && !trimmed.includes("|"))
  );
}

function getProjectLinkStatus(project: ResumeEditorType["projects"][number]): {
  label: string;
  tone: string;
} {
  if (!project.name && !project.url && !project.description) {
    return { label: "Empty", tone: "text-muted-foreground border-border" };
  }
  if (!project.url.trim()) {
    return { label: "Missing link", tone: "text-[var(--terminal-yellow)] border-[var(--terminal-yellow)]/30" };
  }
  if (!looksLikeUrl(project.url)) {
    return { label: "Check URL", tone: "text-destructive border-destructive/30" };
  }
  return { label: "Link detected", tone: "text-primary border-primary/30" };
}

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

export function sanitizeResumeEditor(editor: ResumeEditorType): ResumeEditorType {
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

export function validateResumeEditor(editor: ResumeEditorType): string | null {
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

function ResumeSection({
  title,
  description,
  open,
  onToggle,
  actions,
  children,
}: {
  title: string;
  description?: string;
  open: boolean;
  onToggle: () => void;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-border pt-4 first:border-t-0 first:pt-0">
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={onToggle}
          className="flex flex-1 items-start justify-between gap-3 text-left"
        >
          <div>
            <div className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">{title}</div>
            {description ? (
              <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{description}</div>
            ) : null}
          </div>
          <span className="mt-0.5 text-muted-foreground">
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        </button>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
      {open ? <div className="mt-4 space-y-3">{children}</div> : null}
    </section>
  );
}

interface ResumeEditorProps {
  token: string;
  resumeEditor: ResumeEditorType;
  setResumeEditor: React.Dispatch<React.SetStateAction<ResumeEditorType>>;
  resumeTemplate: string;
  setResumeTemplate: (v: string) => void;
  resumeTemplates: string[];
  onLoad: () => Promise<void>;
}

export function ResumeEditorComponent({
  token,
  resumeEditor,
  setResumeEditor,
  resumeTemplate,
  setResumeTemplate,
  resumeTemplates,
  onLoad,
}: ResumeEditorProps) {
  const { toast } = useToast();

  const [previewingResume, setPreviewingResume] = useState(false);
  const [resumePreviewMeta, setResumePreviewMeta] = useState<{
    pageCount: number;
    warnings: string[];
    fitActions: string[];
    openedAt: number;
  } | null>(null);
  const [uploadingResume, setUploadingResume] = useState(false);
  const [resumeSections, setResumeSections] = useState<Record<ResumeWorkspaceSection, boolean>>({
    basics: true,
    summary: true,
    experience: true,
    projects: false,
    skills: false,
    certifications: false,
  });

  const resumeUploadRef = useRef<HTMLInputElement | null>(null);

  function toggleResumeSection(section: ResumeWorkspaceSection) {
    setResumeSections((current) => ({ ...current, [section]: !current[section] }));
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
      setResumePreviewMeta({
        pageCount: preview.page_count,
        warnings: preview.warnings,
        fitActions: preview.fit_actions,
        openedAt: Date.now(),
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
      await onLoad();
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

  return (
    <div className="tab-enter space-y-6">
      <div className="border border-border bg-card">
        <div className="sticky top-14 z-10 border-b border-border bg-card/95 px-5 py-4 backdrop-blur-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <FileText size={13} className="text-primary" />
                <span className="text-[11px] uppercase tracking-[0.15em] text-muted-foreground">Resume Workspace</span>
              </div>
              <div className="text-sm text-muted-foreground">
                Edit the document in one place. Open only the sections you need, then preview when the content materially changes.
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="min-w-[132px]">
                <label className="mb-1 block text-[10px] uppercase tracking-wider text-muted-foreground">
                  Theme
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
              <button
                type="button"
                onClick={() => resumeUploadRef.current?.click()}
                disabled={uploadingResume}
                className="inline-flex h-9 items-center gap-2 border border-primary/40 px-3 text-[10px] uppercase tracking-[0.22em] text-primary transition-colors hover:bg-primary/8 disabled:opacity-50"
              >
                {uploadingResume ? <RefreshCw size={10} className="animate-spin" /> : <Upload size={10} />}
                {uploadingResume ? "Uploading..." : "Upload Resume"}
              </button>
              <button
                type="button"
                onClick={handlePreviewResume}
                disabled={previewingResume}
                className="inline-flex h-9 items-center gap-2 border border-border px-3 text-[10px] uppercase tracking-[0.22em] text-foreground transition-colors hover:border-primary/30 hover:bg-primary/8 disabled:opacity-50"
              >
                {previewingResume ? <RefreshCw size={10} className="animate-spin" /> : <Eye size={10} />}
                {previewingResume ? "Opening..." : "Preview"}
              </button>
            </div>
          </div>
          {previewingResume && <ResumePreviewSkeleton />}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
            <span>Preview opens in a new tab.</span>
            <span>Pages: <span className="text-foreground tabular-nums">{resumePreviewMeta?.pageCount ?? "—"}</span></span>
            <span>Warnings: <span className="text-foreground tabular-nums">{resumePreviewMeta?.warnings.length ?? 0}</span></span>
            <span>Fit actions: <span className="text-foreground tabular-nums">{resumePreviewMeta?.fitActions.length ?? 0}</span></span>
            {resumePreviewMeta ? (
              <span>Last preview {new Date(resumePreviewMeta.openedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            ) : null}
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
        <div className="space-y-5 px-5 py-5">
          <ResumeSection
            title="Basics"
            description="Identity, headline, and public profile links."
            open={resumeSections.basics}
            onToggle={() => toggleResumeSection("basics")}
          >
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
                    value={resumeEditor[key as keyof ResumeEditorType] as string}
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
          </ResumeSection>

          <ResumeSection
            title="Summary"
            description="Keep this tight. The preview will tell you whether there is room for more."
            open={resumeSections.summary}
            onToggle={() => toggleResumeSection("summary")}
          >
            <div>
              <textarea
                rows={4}
                value={resumeEditor.summary}
                onChange={(e) => setResumeEditor((current) => ({ ...current, summary: e.target.value }))}
                suppressHydrationWarning
                className="w-full border border-border bg-input px-3 py-2 text-xs text-foreground transition-colors placeholder:text-muted-foreground/40 focus:border-primary focus:outline-none"
              />
              <div className="mt-1 text-[10px] leading-relaxed text-muted-foreground/80">
                Use `**bold**` for emphasis.
              </div>
            </div>
          </ResumeSection>

          <ResumeSection
            title="Experience"
            description="Your core content. Keep this open most of the time."
            open={resumeSections.experience}
            onToggle={() => toggleResumeSection("experience")}
            actions={(
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
            )}
          >
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
          </ResumeSection>

          <ResumeSection
            title="Projects"
            description="Keep project links valid so the exported PDF retains them."
            open={resumeSections.projects}
            onToggle={() => toggleResumeSection("projects")}
            actions={(
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
            )}
          >
            {resumeEditor.projects.map((project, index) => (
              <div key={`project-${index}`} className="space-y-3 border border-border p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Project {index + 1}</div>
                  <span className={`border px-2 py-1 text-[10px] uppercase tracking-[0.18em] ${getProjectLinkStatus(project).tone}`}>
                    {getProjectLinkStatus(project).label}
                  </span>
                </div>
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
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      Add the public project URL here so the PDF can keep it clickable.
                    </div>
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
          </ResumeSection>

          <ResumeSection
            title="Skills"
            description="Collapsed by default because this section is usually edited less often."
            open={resumeSections.skills}
            onToggle={() => toggleResumeSection("skills")}
            actions={(
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
            )}
          >
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
          </ResumeSection>

          <ResumeSection
            title="Certifications"
            description="Optional. Keep one certification per line."
            open={resumeSections.certifications}
            onToggle={() => toggleResumeSection("certifications")}
          >
            <div>
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
            </div>
          </ResumeSection>
        </div>
      </div>
    </div>
  );
}

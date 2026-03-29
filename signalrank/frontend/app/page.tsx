import Link from "next/link";
import { auth } from "@/auth";
import {
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Clock3,
  Layers3,
  Radar,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  WandSparkles,
} from "lucide-react";

const featureCards = [
  {
    icon: Target,
    title: "Intent-aware onboarding",
    body: "Resume parsing, role inference, seniority detection, and location targeting feed the ranking stack instead of living as dead profile fields.",
  },
  {
    icon: Search,
    title: "Role-aligned scraping",
    body: "Fast refreshes keep momentum high. Wider lookback windows and deeper full scans stay available when you want older or broader coverage.",
  },
  {
    icon: BrainCircuit,
    title: "Deterministic ranking",
    body: "Signals, role clusters, exclusions, and penalties keep irrelevant jobs from outranking strong matches.",
  },
  {
    icon: ClipboardList,
    title: "Actionable workflow",
    body: "High-fit jobs move into the tracker, recruiter discovery stays attached to companies, and tailored resumes stay close to each job.",
  },
];

const principles = [
  "Make role intent explicit before scraping.",
  "Show the scan window clearly so users can widen or tighten coverage.",
  "Rank by fit, not by noisy keyword overlap alone.",
];

const walkthrough = [
  {
    step: "01",
    title: "Model the search correctly",
    body: "Onboarding captures roles, seniority, locations, exclusions, and resume-derived preferences before the first scan runs.",
    meta: "Resume parse + manual correction",
  },
  {
    step: "02",
    title: "Scan with controlled breadth",
    body: "Use quick refreshes for speed or increase the lookback window in Settings when you want a deeper pass through older listings.",
    meta: "24h quick scan or wider full run",
  },
  {
    step: "03",
    title: "Act on ranked output",
    body: "Review top matches, generate tailored resumes, find recruiters, and push strong roles into the tracker without leaving the flow.",
    meta: "Jobs + tracker + resumes + outreach",
  },
];

export default async function HomePage() {
  const session = await auth();
  const isAuthed = Boolean(session);
  const primaryHref = isAuthed ? "/dashboard" : "/signup";
  const primaryLabel = isAuthed ? "Open dashboard" : "Start free";

  return (
    <main className="min-h-screen page-content">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-4 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
        <section className="relative overflow-hidden border border-border bg-card">
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute inset-0 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--card)_78%,transparent),transparent_55%,color-mix(in_srgb,var(--primary)_8%,transparent))]" />
            <div className="absolute -left-16 top-20 h-56 w-56 rounded-full bg-[color-mix(in_srgb,var(--primary)_16%,transparent)] blur-3xl" />
            <div className="absolute right-0 top-0 h-72 w-72 rounded-full bg-[color-mix(in_srgb,var(--terminal-yellow)_10%,transparent)] blur-3xl" />
            <div className="absolute inset-0 opacity-40 bg-[radial-gradient(circle_at_1px_1px,color-mix(in_srgb,var(--primary)_12%,transparent)_1px,transparent_1px)] bg-[length:24px_24px]" />
          </div>

          <div className="relative grid gap-8 px-6 py-8 sm:px-8 sm:py-10 lg:grid-cols-[1.15fr_0.85fr] lg:px-10 lg:py-12">
            <div className="space-y-7">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center gap-2 border border-primary/30 bg-primary/8 px-3 py-1.5 text-[10px] uppercase tracking-[0.3em] text-primary">
                  <Sparkles size={10} />
                  Job search operating system
                </div>
                <div className="inline-flex items-center gap-2 border border-border bg-background/70 px-3 py-1.5 text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
                  <ShieldCheck size={10} className="text-primary" />
                  Ranking first, scraping second
                </div>
              </div>

              <div className="space-y-5">
                <h1 className="max-w-4xl text-4xl font-bold tracking-[-0.06em] leading-[0.9] text-foreground sm:text-5xl lg:text-7xl">
                  Stop scrolling through job noise.
                  <span className="block text-primary">Build a feed that understands your target.</span>
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">
                  SignalRank turns onboarding, role intent, scrape controls, ranking, recruiter discovery, tracking, and resume tailoring into one loop. The result is a smaller set of jobs that is easier to trust and faster to act on.
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <Link
                  href={primaryHref}
                  className="inline-flex items-center gap-2 border border-primary bg-primary px-5 py-3 text-xs font-bold uppercase tracking-[0.22em] text-primary-foreground transition-all hover:opacity-90"
                >
                  {primaryLabel}
                  <ArrowRight size={14} />
                </Link>
                <Link
                  href={isAuthed ? "/settings" : "/login"}
                  className="inline-flex items-center gap-2 border border-border bg-background/65 px-5 py-3 text-xs font-bold uppercase tracking-[0.22em] text-foreground transition-colors hover:border-primary/50 hover:text-primary"
                >
                  {isAuthed ? "Tune settings" : "Sign in"}
                </Link>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { label: "Input", value: "Resume + target roles + exclusions" },
                  { label: "Control", value: "Quick scans or wider lookback windows" },
                  { label: "Output", value: "Ranked jobs, tracker, resumes, recruiters" },
                ].map((item) => (
                  <div key={item.label} className="border border-border bg-background/70 p-4">
                    <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">{item.label}</div>
                    <div className="mt-2 text-sm font-medium leading-6 text-foreground">{item.value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-4">
              <div className="border border-border bg-background/75 p-5 shadow-[0_0_0_1px_color-mix(in_srgb,var(--primary)_6%,transparent)]">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Live system model</div>
                    <div className="text-lg font-semibold text-foreground">What makes the feed relevant</div>
                  </div>
                  <Radar size={16} className="text-primary" />
                </div>

                <div className="mt-5 space-y-4">
                  <div className="space-y-2">
                    {[
                      { label: "Role intent", value: "SAP SD Consultant" },
                      { label: "Locations", value: "Bangalore, Hyderabad, Remote" },
                      { label: "Lookback", value: "24h quick scan / 168h deep run" },
                    ].map((row) => (
                      <div key={row.label} className="flex items-center justify-between gap-4 border-b border-border/50 pb-2 last:border-0 last:pb-0">
                        <span className="text-[10px] uppercase tracking-[0.24em] text-muted-foreground">{row.label}</span>
                        <span className="text-xs font-medium text-foreground text-right">{row.value}</span>
                      </div>
                    ))}
                  </div>

                  <div className="rounded-none border border-primary/20 bg-primary/6 p-4">
                    <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-primary">
                      <Clock3 size={10} />
                      Search window is explicit
                    </div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      Users can widen the scrape window later in Settings instead of guessing why older jobs are missing.
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  { label: "Quick refresh", value: "Fast signal check against fresh jobs", icon: Search },
                  { label: "Full run", value: "Broader pass across roles, sources, and time", icon: Layers3 },
                  { label: "Ranking", value: "Role clusters, penalties, and score signals", icon: BrainCircuit },
                  { label: "Execution", value: "Tracker, recruiter search, and resume tailoring", icon: WandSparkles },
                ].map(({ label, value, icon: Icon }) => (
                  <div key={label} className="border border-border bg-card p-4">
                    <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
                      <Icon size={11} className="text-primary" />
                      {label}
                    </div>
                    <div className="mt-3 text-sm font-medium leading-6 text-foreground">{value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-3 border border-border bg-card px-5 py-5 sm:grid-cols-3 sm:px-6">
          {principles.map((line) => (
            <div key={line} className="flex items-start gap-3">
              <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-primary" />
              <p className="text-sm leading-6 text-foreground">{line}</p>
            </div>
          ))}
        </section>

        <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="border border-border bg-card p-6">
            <div className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Why it converts better</div>
            <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-foreground">
              The landing page should explain the product in the same order the product works.
            </h2>
            <p className="mt-4 text-sm leading-7 text-muted-foreground">
              Good job-search UX is mostly about reducing ambiguity. Users need to understand what the system uses as input, how broad the scan is, why jobs rank the way they do, and what action they can take next. That story now starts above the fold instead of being scattered across feature cards.
            </p>
            <div className="mt-6 space-y-3">
              {walkthrough.map(({ step, title, body, meta }) => (
                <div key={step} className="border border-border bg-background/65 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-[10px] uppercase tracking-[0.28em] text-primary">{step}</span>
                    <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">{meta}</span>
                  </div>
                  <div className="mt-2 text-base font-medium text-foreground">{title}</div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {featureCards.map(({ icon: Icon, title, body }) => (
              <div key={title} className="border border-border bg-card p-5 transition-colors hover:border-primary/35">
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center border border-primary/20 bg-primary/8 text-primary">
                    <Icon size={14} />
                  </div>
                  <h3 className="text-sm font-semibold tracking-[0.01em] text-foreground">{title}</h3>
                </div>
                <p className="mt-4 text-sm leading-7 text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border border-border bg-card p-6 sm:p-7">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl space-y-3">
              <div className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Call to action</div>
              <h2 className="text-2xl font-semibold tracking-[-0.04em] text-foreground sm:text-3xl">
                Start with a narrow, explainable feed. Widen the search only when you want to.
              </h2>
              <p className="text-sm leading-7 text-muted-foreground">
                The product is strongest when the user can see how intent, scan depth, and ranking interact. The landing page now makes that explicit before signup.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Link
                href={primaryHref}
                className="inline-flex items-center gap-2 border border-primary bg-primary px-5 py-3 text-xs font-bold uppercase tracking-[0.22em] text-primary-foreground transition-colors hover:opacity-90"
              >
                {primaryLabel}
                <ChevronRight size={14} />
              </Link>
              <Link
                href={isAuthed ? "/settings" : "/login"}
                className="inline-flex items-center gap-2 border border-border bg-background/65 px-5 py-3 text-xs font-bold uppercase tracking-[0.22em] text-foreground transition-colors hover:border-primary/50 hover:text-primary"
              >
                {isAuthed ? "Review settings" : "Sign in"}
              </Link>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

import Link from "next/link";
import { auth } from "@/auth";
import {
  ArrowRight,
  BarChart3,
  BrainCircuit,
  ClipboardList,
  Clock3,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  WandSparkles,
} from "lucide-react";

const features = [
  {
    icon: Target,
    title: "Intent-aware onboarding",
    body: "Select the roles, seniority, and locations that actually define your search, then let the app carry that intent through ranking and scraping.",
  },
  {
    icon: Search,
    title: "Role-aligned scraping",
    body: "Quick refreshes stay fast, while full runs can search further back in time and across more sources when you need broader coverage.",
  },
  {
    icon: BrainCircuit,
    title: "Deterministic ranking",
    body: "Jobs are scored with signal weights, role clusters, and penalties so generic noise stops bubbling into your top results.",
  },
  {
    icon: WandSparkles,
    title: "Resume tailoring",
    body: "Generate targeted resumes and outreach from the same profile context you use for ranking and onboarding.",
  },
  {
    icon: ClipboardList,
    title: "Tracker and applications",
    body: "Move interesting jobs into the tracker, keep status changes in one place, and avoid losing high-fit roles between runs.",
  },
  {
    icon: BarChart3,
    title: "Analytics and recruiter tools",
    body: "Review match quality, run history, recruiter discovery, and company-level insights without leaving the app.",
  },
];

const flow = [
  {
    step: "01",
    title: "Set your target",
    body: "Pick your roles, locations, compensation band, and search window in onboarding or Settings.",
  },
  {
    step: "02",
    title: "Run a scan",
    body: "Trigger a quick refresh or a deeper background run when you want wider coverage.",
  },
  {
    step: "03",
    title: "Act on the best matches",
    body: "Review ranked jobs, tailor your resume, save recruiters, and push good fits into the tracker.",
  },
];

export default async function HomePage() {
  const session = await auth();
  const isAuthed = Boolean(session);

  return (
    <main className="min-h-screen page-content">
      <div className="max-w-6xl mx-auto px-6 py-8 lg:py-14 space-y-10">
        <section className="relative overflow-hidden border border-border bg-card">
          <div className="absolute inset-0 pointer-events-none">
            <div className="absolute -top-24 right-0 h-72 w-72 rounded-full bg-[color-mix(in_srgb,var(--primary)_16%,transparent)] blur-3xl" />
            <div className="absolute bottom-0 left-0 h-72 w-72 rounded-full bg-[color-mix(in_srgb,var(--terminal-yellow)_12%,transparent)] blur-3xl" />
            <div className="absolute inset-0 opacity-50 bg-[radial-gradient(circle_at_1px_1px,color-mix(in_srgb,var(--primary)_12%,transparent)_1px,transparent_1px)] bg-[length:24px_24px]" />
          </div>

          <div className="relative grid gap-8 p-8 lg:p-12 lg:grid-cols-[1.2fr_0.8fr] items-center">
            <div className="space-y-6">
              <div className="inline-flex items-center gap-2 border border-primary/30 bg-primary/5 px-3 py-1 text-[10px] uppercase tracking-[0.3em] text-primary">
                <Sparkles size={10} />
                Job intelligence terminal
              </div>

              <div className="space-y-4">
                <h1 className="max-w-3xl text-4xl font-bold tracking-[-0.05em] leading-[0.92] text-foreground lg:text-6xl">
                  Find relevant jobs,
                  <span className="text-primary"> not just more jobs.</span>
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-muted-foreground lg:text-base">
                  SignalRank turns your resume into a structured search profile, ranks jobs by fit, lets you widen the scrape window when you want older listings, and keeps the rest of the workflow in one place: onboarding, scanning, tracking, tailoring, recruiter discovery, and analytics.
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <Link
                  href={isAuthed ? "/dashboard" : "/signup"}
                  className="inline-flex items-center gap-2 border border-primary bg-primary px-4 py-2 text-xs font-bold uppercase tracking-wider text-primary-foreground transition-colors hover:opacity-90"
                >
                  {isAuthed ? "Open dashboard" : "Get started"}
                  <ArrowRight size={13} />
                </Link>
                <Link
                  href="/login"
                  className="inline-flex items-center gap-2 border border-border bg-transparent px-4 py-2 text-xs font-bold uppercase tracking-wider text-primary transition-colors hover:bg-primary/10"
                >
                  Sign in
                </Link>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { label: "Onboarding", value: "Resume + role intent" },
                  { label: "Scrape window", value: "24h quick, wider on demand" },
                  { label: "Outputs", value: "Jobs, tracker, resumes, email" },
                ].map((item) => (
                  <div key={item.label} className="border border-border bg-background/70 p-4">
                    <div className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground">{item.label}</div>
                    <div className="mt-2 text-sm font-medium text-foreground">{item.value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-4">
              <div className="border border-border bg-background/70 p-5">
                <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.25em] text-muted-foreground">
                  <ShieldCheck size={12} className="text-primary" />
                  What it handles
                </div>
                <div className="mt-4 space-y-3">
                  {[
                    "Target roles and seniority captured during onboarding",
                    "Manual Settings control for locations, lookback, and query depth",
                    "Quick refreshes for fast feedback and full runs for broader coverage",
                    "Ranked jobs, recruiter discovery, tracker import, and resume tailoring",
                  ].map((line) => (
                    <div key={line} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                      <span>{line}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  { label: "Quick scan", value: "Indeed-first, 24h lookback" },
                  { label: "Deep scan", value: "Full background run, wider window" },
                  { label: "Ranking", value: "Role clusters + penalties" },
                  { label: "Recruiters", value: "Search, save, and track" },
                ].map((item) => (
                  <div key={item.label} className="border border-border bg-card p-4">
                    <div className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground">{item.label}</div>
                    <div className="mt-2 text-sm font-medium text-foreground">{item.value}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-3 sm:grid-cols-3">
          {flow.map(({ step, title, body }) => (
            <div key={step} className="border border-border bg-card p-5">
              <div className="text-[10px] uppercase tracking-[0.3em] text-primary">{step}</div>
              <h2 className="mt-3 text-lg font-semibold text-foreground">{title}</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
            </div>
          ))}
        </section>

        <section className="space-y-4">
          <div className="section-label">features</div>
          <div className="grid gap-3 md:grid-cols-2">
            {features.map(({ icon: Icon, title, body }) => (
              <div key={title} className="border border-border bg-card p-5">
                <div className="flex items-center gap-2">
                  <Icon size={13} className="text-primary" />
                  <h3 className="text-sm font-semibold text-foreground">{title}</h3>
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border border-border bg-card p-5 lg:p-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">scan control</div>
              <h2 className="text-xl font-semibold text-foreground">Need older jobs? Increase the lookback window in Settings.</h2>
              <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
                The Settings page makes the scrape window explicit so you can widen future runs when you want more history, or keep it tight for fast refreshes.
              </p>
            </div>
            <Link
              href={isAuthed ? "/dashboard" : "/signup"}
              className="inline-flex items-center gap-2 border border-primary bg-primary px-4 py-2 text-xs font-bold uppercase tracking-wider text-primary-foreground transition-colors hover:opacity-90"
            >
              {isAuthed ? "Continue" : "Start scanning"}
              <Clock3 size={13} />
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}

import Link from "next/link";
import { auth } from "@/auth";
import {
  ArrowRight,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Mail,
  Radar,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  WandSparkles,
} from "lucide-react";

const featureCards = [
  {
    title: "Tailored resume and recruiter email",
    body: "Each strong match can turn into a job-specific PDF plus a ready-to-send recruiter draft instead of another tab you promise to revisit later.",
    icon: WandSparkles,
  },
  {
    title: "Intent-aware onboarding",
    body: "Resume parsing, role inference, seniority detection, and location targeting shape the search before the first run happens.",
    icon: Target,
  },
  {
    title: "Role-aligned scraping",
    body: "Quick scans stay fast. Wider lookback windows and more titles stay available in Settings when you want broader coverage.",
    icon: Search,
  },
  {
    title: "Tracker attached to execution",
    body: "Top jobs, recruiter discovery, status updates, notes, and outreach all sit in one flow instead of being spread across spreadsheets and drafts.",
    icon: ClipboardList,
  },
];

const proofTiles = [
  {
    label: "Match selected",
    value: "Sr Staff ML Engineer",
    sub: "Top-ranked job promoted into action",
  },
  {
    label: "Resume output",
    value: "Tailored PDF ready",
    sub: "Generated per job, not one generic export",
  },
  {
    label: "Outreach output",
    value: "Recruiter email drafted",
    sub: "Subject and body created with the job context",
  },
  {
    label: "Control surface",
    value: "Deep scan from Settings",
    sub: "Wider hours and more titles only when needed",
  },
];

const walkthrough = [
  {
    step: "01",
    title: "Define the target clearly",
    body: "Resume parsing and manual correction make the role, seniority, locations, and exclusions explicit before the system starts scanning.",
    meta: "Resume + target roles + preferences",
  },
  {
    step: "02",
    title: "Keep retrieval tight by default",
    body: "Use fast scans for fresh jobs, then widen hours or title breadth only from Settings when you want a deeper pass through the market.",
    meta: "Quick scan first, deep scan deliberately",
  },
  {
    step: "03",
    title: "Turn fit into action",
    body: "Promote a ranked job into the tracker, generate a tailored resume, draft the recruiter email, and move directly into outreach.",
    meta: "Tracker + tailored resume + mail",
  },
];

const principles = [
  "Lead with the action users want most: tailored resume plus recruiter email.",
  "Borrow proof modules from the dashboard, not the whole authenticated dashboard.",
  "Make scan depth explicit so users know when to widen time range or title coverage.",
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
          <div className="pointer-events-none absolute inset-0">
            <div className="absolute inset-0 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--card)_76%,transparent),transparent_52%,color-mix(in_srgb,var(--primary)_10%,transparent))]" />
            <div className="absolute -left-10 top-16 h-56 w-56 rounded-full bg-[color-mix(in_srgb,var(--primary)_14%,transparent)] blur-3xl" />
            <div className="absolute right-0 top-0 h-72 w-72 rounded-full bg-[color-mix(in_srgb,var(--terminal-yellow)_10%,transparent)] blur-3xl" />
            <div className="absolute inset-0 opacity-35 bg-[radial-gradient(circle_at_1px_1px,color-mix(in_srgb,var(--primary)_12%,transparent)_1px,transparent_1px)] bg-[length:24px_24px]" />
          </div>

          <div className="relative grid gap-8 px-6 py-8 sm:px-8 sm:py-10 lg:grid-cols-[1.08fr_0.92fr] lg:px-10 lg:py-12">
            <div className="space-y-7">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center gap-2 border border-primary/30 bg-primary/8 px-3 py-1.5 text-[10px] uppercase tracking-[0.3em] text-primary">
                  <Sparkles size={10} />
                  Application execution system
                </div>
                <div className="inline-flex items-center gap-2 border border-border bg-background/70 px-3 py-1.5 text-[10px] uppercase tracking-[0.28em] text-muted-foreground">
                  <ShieldCheck size={10} className="text-primary" />
                  Search, rank, tailor, email
                </div>
              </div>

              <div className="space-y-5">
                <h1 className="max-w-4xl text-4xl font-bold tracking-[-0.06em] leading-[0.9] text-foreground sm:text-5xl lg:text-7xl">
                  Tailor the resume.
                  <span className="block text-primary">Draft the recruiter email.</span>
                  <span className="block">Then apply from a feed that already fits.</span>
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">
                  SignalRank is strongest when ranking turns directly into execution. The landing page now leads with the highest-value loop: find a relevant job, generate the tailored resume, open the recruiter email draft, and keep the next action in the tracker.
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
                  href={isAuthed ? "/tracker" : "/login"}
                  className="inline-flex items-center gap-2 border border-border bg-background/65 px-5 py-3 text-xs font-bold uppercase tracking-[0.22em] text-foreground transition-colors hover:border-primary/50 hover:text-primary"
                >
                  {isAuthed ? "Open tracker" : "Sign in"}
                </Link>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { label: "Input", value: "Resume, role intent, exclusions" },
                  { label: "Decision", value: "Quick scan first, deep scan in settings" },
                  { label: "Output", value: "Tailored resume, recruiter mail, tracker" },
                ].map((item) => (
                  <div key={item.label} className="border border-border bg-background/70 p-4">
                    <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">{item.label}</div>
                    <div className="mt-2 text-sm font-medium leading-6 text-foreground">{item.value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-4">
              <div className="border border-border bg-background/80 p-5 shadow-[0_0_0_1px_color-mix(in_srgb,var(--primary)_7%,transparent)]">
                <div className="flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Hero proof panel</div>
                    <div className="text-lg font-semibold text-foreground">Application package, ready</div>
                  </div>
                  <WandSparkles size={16} className="text-primary" />
                </div>

                <div className="mt-5 space-y-4">
                  <div className="border border-border bg-card p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">Senior Software Engineer, Agentic AI</div>
                        <div className="mt-1 text-[11px] uppercase tracking-[0.22em] text-muted-foreground">Autodesk • SS tier • top match</div>
                      </div>
                      <div className="border border-primary/25 bg-primary/8 px-2.5 py-1 text-[10px] uppercase tracking-[0.22em] text-primary">
                        79 fit
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="border border-border bg-card p-4">
                      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-primary">
                        <BriefcaseBusiness size={10} />
                        Tailored resume
                      </div>
                      <div className="mt-3 space-y-2 text-sm text-foreground">
                        <div className="flex items-center gap-2">
                          <CheckCircle2 size={13} className="text-primary" />
                          Job-specific summary
                        </div>
                        <div className="flex items-center gap-2">
                          <CheckCircle2 size={13} className="text-primary" />
                          Reweighted experience bullets
                        </div>
                        <div className="flex items-center gap-2">
                          <CheckCircle2 size={13} className="text-primary" />
                          PDF ready for download
                        </div>
                      </div>
                    </div>

                    <div className="border border-border bg-card p-4">
                      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-primary">
                        <Mail size={10} />
                        Recruiter email
                      </div>
                      <div className="mt-3 space-y-2 text-sm leading-6 text-muted-foreground">
                        <p className="text-foreground">Subject: Agentic AI role at Autodesk</p>
                        <p>Hi Priya, I applied for the role and wanted to reach out directly because my background aligns with the platform and agentic systems work...</p>
                        <p className="text-primary">Open Gmail compose with draft attached to the job.</p>
                      </div>
                    </div>
                  </div>

                  <div className="rounded-none border border-primary/20 bg-primary/6 p-4">
                    <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-primary">
                      <Radar size={10} />
                      Borrowed from the dashboard, compressed for landing
                    </div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      The landing page should show proof of the product loop, not the entire logged-in dashboard. These cards give enough evidence without turning the home page into an admin screen.
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {proofTiles.map((tile) => (
                  <div key={tile.label} className="border border-border bg-card p-4">
                    <div className="text-[10px] uppercase tracking-[0.24em] text-muted-foreground">{tile.label}</div>
                    <div className="mt-3 text-sm font-medium leading-6 text-foreground">{tile.value}</div>
                    <div className="mt-2 text-xs leading-5 text-muted-foreground">{tile.sub}</div>
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
            <div className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">Product flow</div>
            <h2 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-foreground">
              The home page should explain the same loop the product executes.
            </h2>
            <p className="mt-4 text-sm leading-7 text-muted-foreground">
              Yes, some dashboard ideas belong on the landing page, but only as tight proof blocks. Bring the best evidence forward: match quality, tailored output, email execution, and scan controls. Leave raw tables, admin controls, and dense analytics inside the authenticated app.
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
                Use the landing page to promise outcomes. Use the product to prove them instantly.
              </h2>
              <p className="text-sm leading-7 text-muted-foreground">
                The revised hero centers the most valuable output and the updated run flow now surfaces queued scans immediately in settings, runs, and dashboard without waiting for a manual refresh.
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

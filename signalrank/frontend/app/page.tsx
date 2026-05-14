import Link from "next/link";
import { auth } from "@/auth";
import { redirect } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  Mail,
  Search,
  Sparkles,
  Target,
  WandSparkles,
} from "lucide-react";

const features = [
  {
    title: "Tailored resume",
    body: "Generate a job-specific PDF from the roles you actually want.",
    icon: WandSparkles,
  },
  {
    title: "Recruiter email draft",
    body: "Open a prewritten outreach draft with the right job context.",
    icon: Mail,
  },
  {
    title: "Role-aware search",
    body: "Scan, rank, and filter jobs using your resume and target roles.",
    icon: Search,
  },
  {
    title: "Tracker built in",
    body: "Keep applications, notes, statuses, and outreach in one place.",
    icon: ClipboardList,
  },
];

export default async function HomePage() {
  if (process.env.NEXT_PUBLIC_SIGNALRANK_MODE === "desktop") {
    redirect("/desktop-setup");
  }

  const session = await auth();
  const isAuthed = Boolean(session);
  const primaryHref = isAuthed ? "/dashboard" : "/signup";
  const primaryLabel = isAuthed ? "Open dashboard" : "Start free";

  return (
    <main className="min-h-screen page-content">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-4 sm:px-6 sm:py-6 lg:px-8 lg:py-8">
        <section className="relative overflow-hidden border border-border bg-card">
          <div className="pointer-events-none absolute inset-0">
            <div className="absolute inset-0 bg-[linear-gradient(135deg,color-mix(in_srgb,var(--card)_80%,transparent),transparent_54%,color-mix(in_srgb,var(--primary)_9%,transparent))]" />
            <div className="absolute -left-12 top-16 h-56 w-56 rounded-full bg-[color-mix(in_srgb,var(--primary)_14%,transparent)] blur-3xl" />
            <div className="absolute right-0 top-0 h-72 w-72 rounded-full bg-[color-mix(in_srgb,var(--terminal-yellow)_10%,transparent)] blur-3xl" />
          </div>

          <div className="relative grid gap-8 px-6 py-8 sm:px-8 sm:py-10 lg:grid-cols-[1.05fr_0.95fr] lg:px-10 lg:py-12">
            <div className="space-y-6">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center gap-2 border border-primary/30 bg-primary/8 px-3 py-1.5 text-[10px] uppercase tracking-[0.3em] text-primary">
                  <Sparkles size={10} />
                  Job search, compressed
                </div>
              </div>

              <div className="space-y-4">
                <h1 className="max-w-4xl text-4xl font-bold tracking-[-0.06em] leading-[0.92] text-foreground sm:text-5xl lg:text-7xl">
                  Tailor the resume.
                  <span className="block text-primary">Draft the email.</span>
                  <span className="block">Apply faster.</span>
                </h1>
                <p className="max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">
                  SignalRank finds relevant jobs, generates a tailored resume, drafts recruiter outreach, and keeps the next step in the tracker.
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
                  { label: "Input", value: "Resume + target roles" },
                  { label: "Flow", value: "Scan, rank, tailor" },
                  { label: "Output", value: "PDF, email, tracker" },
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
                    <div className="text-[10px] uppercase tracking-[0.3em] text-muted-foreground">What you get</div>
                    <div className="text-lg font-semibold text-foreground">One strong match, ready to act on</div>
                  </div>
                  <Target size={16} className="text-primary" />
                </div>

                <div className="mt-5 space-y-3">
                  <div className="border border-border bg-card p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold text-foreground">Senior Software Engineer, Agentic AI</div>
                        <div className="mt-1 text-[11px] uppercase tracking-[0.22em] text-muted-foreground">Autodesk • SS tier</div>
                      </div>
                      <div className="border border-primary/25 bg-primary/8 px-2.5 py-1 text-[10px] uppercase tracking-[0.22em] text-primary">
                        79 fit
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="border border-border bg-card p-4">
                      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-primary">
                        <WandSparkles size={10} />
                        Resume
                      </div>
                      <div className="mt-3 space-y-2 text-sm text-foreground">
                        <div className="flex items-center gap-2">
                          <CheckCircle2 size={13} className="text-primary" />
                          Tailored PDF
                        </div>
                        <div className="flex items-center gap-2">
                          <CheckCircle2 size={13} className="text-primary" />
                          Reweighted bullets
                        </div>
                      </div>
                    </div>

                    <div className="border border-border bg-card p-4">
                      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.24em] text-primary">
                        <Mail size={10} />
                        Outreach
                      </div>
                      <div className="mt-3 space-y-2 text-sm text-foreground">
                        <div className="flex items-center gap-2">
                          <CheckCircle2 size={13} className="text-primary" />
                          Recruiter draft
                        </div>
                        <div className="flex items-center gap-2">
                          <CheckCircle2 size={13} className="text-primary" />
                          Gmail ready
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {features.map(({ icon: Icon, title, body }) => (
            <div key={title} className="border border-border bg-card p-5">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center border border-primary/20 bg-primary/8 text-primary">
                  <Icon size={14} />
                </div>
                <h2 className="text-sm font-semibold text-foreground">{title}</h2>
              </div>
              <p className="mt-4 text-sm leading-6 text-muted-foreground">{body}</p>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}

import { scoreColor } from "@/lib/formatting";
import type { Job } from "@/types";

export function MiniBarChart({
  data,
  maxVal,
  color = "var(--primary)",
}: {
  data: { label: string; count: number }[];
  maxVal: number;
  color?: string;
}) {
  return (
    <div className="space-y-1.5">
      {data.map(({ label, count }) => (
        <div key={label} className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-16 shrink-0 truncate">{label}</span>
          <div className="flex-1 h-1.5 bg-muted relative overflow-hidden">
            <div
              className="h-full transition-all duration-500"
              style={{ width: `${(count / maxVal) * 100}%`, background: color }}
            />
          </div>
          <span className="text-xs text-muted-foreground tabular-nums w-6 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

export function ScoreDisplay({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = scoreColor(score * 100);
  return (
    <div className="flex flex-col items-end gap-1.5 shrink-0">
      <span className="text-base font-bold tabular-nums leading-none" style={{ color }}>
        {pct}
      </span>
      <div className="score-bar w-16">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}88, ${color})` }} />
      </div>
    </div>
  );
}

export function explainJob(job: Job): string[] {
  const reasons: string[] = [];
  if ((job.semantic_score ?? 0) >= 0.78) reasons.push("strong title fit");
  if ((job.skills_score ?? 0) >= 0.65) reasons.push("skills align");
  if ((job.location_score ?? 0) >= 0.7) reasons.push("location fit");
  if ((job.company_score ?? 0) >= 0.65 || job.company_tier === "tier_ss" || job.company_tier === "tier_s") {
    reasons.push("company signal");
  }
  if ((job.recency_score ?? 0) >= 0.7) reasons.push("fresh posting");
  return reasons.slice(0, 3);
}

export function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  accent = false,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  accent?: boolean;
}) {
  return (
    <div className="stat-card card-hover border border-border bg-card p-5 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">{label}</span>
        <Icon size={12} className={accent ? "text-primary" : "text-muted-foreground"} />
      </div>
      <div className={`text-3xl font-bold tabular-nums leading-none ${accent ? "text-primary text-glow-dim" : "text-foreground"}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-muted-foreground leading-snug">{sub}</div>}
    </div>
  );
}

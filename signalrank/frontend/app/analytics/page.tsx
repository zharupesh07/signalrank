"use client";

import { useEffect, useMemo, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { swr } from "@/lib/cache";
import type { Application, TrackerStats } from "@/types";
import {
  BarChart2,
  GitBranch,
  TrendingUp,
  Layers,
  Target,
} from "lucide-react";
import { ChartSkeleton } from "@/components/skeleton";

type Analytics = {
  score_distribution: { range: string; count: number }[];
  top_companies: { company: string; count: number }[];
  sites: { site: string; count: number }[];
  total: number;
};

const EMPTY_APPLICATIONS: Application[] = [];

const STATUS_COLORS: Record<string, string> = {
  interested: "var(--muted-foreground)",
  applied: "var(--primary)",
  phone_screen: "var(--terminal-green-bright)",
  interview: "var(--chart-3)",
  offer: "var(--chart-2)",
  rejected: "var(--destructive)",
  archived: "var(--border)",
};

const TIER_COLORS: Record<string, string> = {
  tier_ss: "var(--primary)",
  tier_s: "var(--terminal-green-bright)",
  tier_a: "#4ade80",
  tier_b: "var(--terminal-yellow)",
  tier_c: "#f97316",
  tier_d: "var(--muted-foreground)",
  unknown: "var(--border)",
};

function SankeyDiagram({
  applications,
}: {
  applications: Application[];
}) {
  const [hovered, setHovered] = useState<string | null>(null);

  const { nodes, links, svgWidth, svgHeight } = useMemo(() => {
    if (applications.length === 0) return { nodes: [], links: [], svgWidth: 0, svgHeight: 0 };

    const tierCounts: Record<string, number> = {};
    const statusCounts: Record<string, number> = {};
    const flowCounts: Record<string, number> = {};

    for (const app of applications) {
      const tier = app.company_tier
        ? app.company_tier.replace("tier_", "").toUpperCase()
        : "Unknown";
      const status = app.status.replace("_", " ");
      tierCounts[tier] = (tierCounts[tier] ?? 0) + 1;
      statusCounts[status] = (statusCounts[status] ?? 0) + 1;
      flowCounts[`${tier}|||${status}`] = (flowCounts[`${tier}|||${status}`] ?? 0) + 1;
    }

    const tierOrder = ["SS", "S", "A", "B", "C", "D", "DEFAULT", "Unknown"];
    const statusOrder = ["interested", "applied", "phone screen", "interview", "offer", "rejected", "archived"];
    const sortedTiers = Object.keys(tierCounts).sort(
      (a, b) => (tierOrder.indexOf(a) === -1 ? 99 : tierOrder.indexOf(a)) - (tierOrder.indexOf(b) === -1 ? 99 : tierOrder.indexOf(b))
    );
    const sortedStatuses = Object.keys(statusCounts).sort(
      (a, b) => (statusOrder.indexOf(a) === -1 ? 99 : statusOrder.indexOf(a)) - (statusOrder.indexOf(b) === -1 ? 99 : statusOrder.indexOf(b))
    );

    const total = applications.length;
    const nodeGap = 14;
    const minNodeH = 18;
    const padTop = 10;
    const padBot = 10;
    const leftLabelW = 90;
    const rightLabelW = 110;
    const chartW = 800;
    const leftX = leftLabelW;
    const rightX = chartW - rightLabelW;

    const leftCount = sortedTiers.length;
    const rightCount = sortedStatuses.length;
    const availH = (n: number) => Math.max(n * minNodeH + (n - 1) * nodeGap, 220);
    const canvasH = Math.max(availH(leftCount), availH(rightCount));

    type Node = { id: string; x: number; y: number; h: number; color: string; label: string; count: number; side: "left" | "right" };

    function layoutNodes(
      items: { key: string; count: number; color: string }[],
      x: number,
      side: "left" | "right"
    ): Node[] {
      const usableH = canvasH - padTop - padBot - (items.length - 1) * nodeGap;
      const result: Node[] = [];
      let y = padTop;
      for (const item of items) {
        const h = Math.max(minNodeH, (item.count / total) * usableH);
        result.push({ id: `${side[0]}-${item.key}`, x, y, h, color: item.color, label: item.key, count: item.count, side });
        y += h + nodeGap;
      }
      return result;
    }

    const leftNodes = layoutNodes(
      sortedTiers.map((t) => ({
        key: t,
        count: tierCounts[t],
        color: TIER_COLORS[`tier_${t.toLowerCase()}`] ?? TIER_COLORS.unknown,
      })),
      leftX,
      "left"
    );

    const rightNodes = layoutNodes(
      sortedStatuses.map((s) => ({
        key: s,
        count: statusCounts[s],
        color: STATUS_COLORS[s.replace(" ", "_")] ?? "var(--border)",
      })),
      rightX,
      "right"
    );

    const allNodes = [...leftNodes, ...rightNodes];

    type Link = { id: string; source: Node; target: Node; value: number; sy: number; ty: number; thickness: number; color: string };
    const allLinks: Link[] = [];
    const leftOff: Record<string, number> = {};
    const rightOff: Record<string, number> = {};
    for (const n of leftNodes) leftOff[n.id] = 0;
    for (const n of rightNodes) rightOff[n.id] = 0;

    const sortedFlows = Object.entries(flowCounts).sort((a, b) => b[1] - a[1]);
    for (const [key, count] of sortedFlows) {
      const [tier, status] = key.split("|||");
      const src = leftNodes.find((n) => n.label === tier);
      const tgt = rightNodes.find((n) => n.label === status);
      if (!src || !tgt) continue;

      const thickness = Math.max((count / total) * (canvasH * 0.6), 2);
      const sy = src.y + (leftOff[src.id] ?? 0);
      const ty = tgt.y + (rightOff[tgt.id] ?? 0);
      leftOff[src.id] = (leftOff[src.id] ?? 0) + thickness;
      rightOff[tgt.id] = (rightOff[tgt.id] ?? 0) + thickness;

      allLinks.push({ id: key, source: src, target: tgt, value: count, sy, ty, thickness, color: src.color });
    }

    const maxY = Math.max(...allNodes.map((n) => n.y + n.h));
    return { nodes: allNodes, links: allLinks, svgWidth: chartW, svgHeight: maxY + padBot + 10 };
  }, [applications]);

  if (applications.length === 0) {
    return (
      <div className="text-center py-8 text-muted-foreground text-xs">
        No application data yet. Track some jobs to see the flow.
      </div>
    );
  }

  const isLinkHighlighted = (link: { source: { id: string }; target: { id: string }; id: string }) => {
    if (!hovered) return false;
    return link.source.id === hovered || link.target.id === hovered || link.id === hovered;
  };

  const isNodeHighlighted = (node: { id: string }) => {
    if (!hovered) return false;
    if (node.id === hovered) return true;
    return links.some((l) => (l.source.id === node.id || l.target.id === node.id) && (l.source.id === hovered || l.target.id === hovered));
  };

  return (
    <div className="overflow-x-auto -mx-2">
      <svg
        width="100%"
        height={svgHeight}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        preserveAspectRatio="xMidYMid meet"
        onMouseLeave={() => setHovered(null)}
      >
        <defs>
          {links.map((link, i) => (
            <linearGradient key={i} id={`grad-${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={link.source.color} stopOpacity={0.5} />
              <stop offset="100%" stopColor={link.target.color} stopOpacity={0.5} />
            </linearGradient>
          ))}
        </defs>

        {links.map((link, i) => {
          const x0 = link.source.x + 10;
          const x1 = link.target.x;
          const sy = link.sy + link.thickness / 2;
          const ty = link.ty + link.thickness / 2;
          const cp1x = x0 + (x1 - x0) * 0.4;
          const cp2x = x0 + (x1 - x0) * 0.6;
          const d = `M${x0},${sy} C${cp1x},${sy} ${cp2x},${ty} ${x1},${ty}`;
          const highlighted = isLinkHighlighted(link);
          const dimmed = hovered && !highlighted;
          return (
            <path
              key={i}
              d={d}
              fill="none"
              stroke={`url(#grad-${i})`}
              strokeWidth={link.thickness}
              opacity={dimmed ? 0.06 : highlighted ? 0.6 : 0.25}
              style={{ transition: "opacity 0.2s ease" }}
              onMouseEnter={() => setHovered(link.id)}
              cursor="pointer"
            >
              <title>{`${link.source.label} → ${link.target.label}: ${link.value}`}</title>
            </path>
          );
        })}

        {nodes.map((node) => {
          const highlighted = isNodeHighlighted(node);
          const dimmed = hovered && !highlighted && hovered !== node.id;
          return (
            <g
              key={node.id}
              onMouseEnter={() => setHovered(node.id)}
              cursor="pointer"
              style={{ transition: "opacity 0.2s ease" }}
              opacity={dimmed ? 0.3 : 1}
            >
              <rect
                x={node.x}
                y={node.y}
                width={10}
                height={node.h}
                fill={node.color}
                opacity={0.9}
                rx={2}
              />
              {highlighted && (
                <rect
                  x={node.x - 1}
                  y={node.y - 1}
                  width={12}
                  height={node.h + 2}
                  fill="none"
                  stroke={node.color}
                  strokeWidth={1}
                  opacity={0.4}
                  rx={3}
                />
              )}
              {node.side === "left" ? (
                <text
                  x={node.x - 8}
                  y={node.y + node.h / 2}
                  textAnchor="end"
                  dominantBaseline="central"
                  fontSize={11}
                  fontFamily="var(--font-mono)"
                >
                  <tspan fill={node.color} fontWeight={700}>{node.label}</tspan>
                  <tspan fill="var(--muted-foreground)" fontWeight={400} fontSize={10} dx={4}>{node.count}</tspan>
                </text>
              ) : (
                <text
                  x={node.x + 16}
                  y={node.y + node.h / 2}
                  textAnchor="start"
                  dominantBaseline="central"
                  fontSize={11}
                  fontFamily="var(--font-mono)"
                >
                  <tspan fill={node.color} fontWeight={600}>{node.label}</tspan>
                  <tspan fill="var(--muted-foreground)" fontWeight={400} fontSize={10} dx={4}>{node.count}</tspan>
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function MiniBarChart({
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
          <span className="text-xs text-muted-foreground w-20 shrink-0 truncate">
            {label}
          </span>
          <div className="flex-1 h-2 bg-muted relative overflow-hidden">
            <div
              className="h-full transition-all duration-500"
              style={{ width: `${(count / maxVal) * 100}%`, background: color }}
            />
          </div>
          <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">
            {count}
          </span>
        </div>
      ))}
    </div>
  );
}

function StatCard({
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
        <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">
          {label}
        </span>
        <Icon
          size={12}
          className={accent ? "text-primary" : "text-muted-foreground"}
        />
      </div>
      <div
        className={`text-3xl font-bold tabular-nums leading-none ${accent ? "text-primary text-glow-dim" : "text-foreground"}`}
      >
        {value}
      </div>
      {sub && (
        <div className="text-[11px] text-muted-foreground leading-snug">
          {sub}
        </div>
      )}
    </div>
  );
}

function TierBreakdown({ applications }: { applications: Application[] }) {
  const tiers = useMemo(() => {
    const counts: Record<string, { total: number; applied: number; offers: number }> = {};
    for (const app of applications) {
      const tier = app.company_tier
        ? app.company_tier.replace("tier_", "").toUpperCase()
        : "Unknown";
      if (!counts[tier]) counts[tier] = { total: 0, applied: 0, offers: 0 };
      counts[tier].total++;
      if (app.status !== "interested") counts[tier].applied++;
      if (app.status === "offer") counts[tier].offers++;
    }
    return Object.entries(counts)
      .sort((a, b) => b[1].total - a[1].total);
  }, [applications]);

  if (tiers.length === 0) return null;

  return (
    <div className="space-y-2">
      {tiers.map(([tier, { total, applied, offers }]) => {
        const tierKey = `tier_${tier.toLowerCase()}`;
        const color = TIER_COLORS[tierKey] ?? TIER_COLORS.unknown;
        const conversionRate = total > 0 ? Math.round((applied / total) * 100) : 0;
        return (
          <div key={tier} className="flex items-center gap-3">
            <span className="text-[11px] font-bold w-12 shrink-0" style={{ color }}>
              {tier}
            </span>
            <div className="flex-1 h-1.5 bg-muted overflow-hidden">
              <div
                className="h-full"
                style={{ width: `${(total / Math.max(...tiers.map(([, t]) => t.total), 1)) * 100}%`, background: color }}
              />
            </div>
            <span className="text-[10px] text-muted-foreground tabular-nums w-6 text-right">{total}</span>
            <span className="text-[10px] text-muted-foreground tabular-nums w-10 text-right">{conversionRate}% →</span>
            {offers > 0 && (
              <span className="text-[10px] text-[var(--chart-2)] tabular-nums">{offers} offer{offers > 1 ? "s" : ""}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function AnalyticsPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";

  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [stats, setStats] = useState<TrackerStats | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    Promise.all([
      swr("analytics", () => api.jobs.analytics(token), setAnalytics),
      swr("stats", () => api.applications.stats(token), setStats),
      swr("analytics:apps", () => api.applications.list(token), setApplications),
    ]).finally(() => setLoading(false));
  }, [token]);

  const effectiveAnalytics = token ? analytics : null;
  const effectiveStats = token ? stats : null;
  const effectiveApplications = token ? applications : EMPTY_APPLICATIONS;
  const effectiveLoading = token ? loading : false;

  const conversionRate = useMemo(() => {
    if (!effectiveStats || effectiveStats.total === 0) return null;
    const applied = Object.entries(effectiveStats.by_status)
      .filter(([s]) => s !== "interested")
      .reduce((a, [, c]) => a + c, 0);
    return Math.round((applied / effectiveStats.total) * 100);
  }, [effectiveStats]);

  const avgScore = useMemo(() => {
    const scored = effectiveApplications.filter((a) => a.system_score != null);
    if (scored.length === 0) return null;
    return Math.round(
      (scored.reduce((a, b) => a + (b.system_score ?? 0), 0) / scored.length) * 100
    );
  }, [effectiveApplications]);

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-5xl mx-auto px-6 py-8 space-y-7">
        <div className="space-y-1">
          <div className="section-label">analytics</div>
          <h1 className="text-xl font-bold text-foreground tracking-tight">
            Signal Analytics
          </h1>
        </div>

        {effectiveLoading ? (
          <div className="grid grid-cols-4 gap-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="border border-border bg-card p-5 space-y-3">
                <div className="skeleton h-3 w-24" />
                <div className="skeleton h-8 w-16" />
                <div className="skeleton h-3 w-32" />
              </div>
            ))}
          </div>
        ) : (
          <>
            {/* Stat cards */}
            <div className="grid grid-cols-4 gap-3">
              <StatCard
                label="Total Jobs"
                value={effectiveAnalytics?.total ?? 0}
                sub="across all sources"
                icon={Layers}
                accent
              />
              <StatCard
                label="Tracked"
                value={effectiveStats?.total ?? 0}
                sub={`${effectiveStats?.offers_count ?? 0} offer${(effectiveStats?.offers_count ?? 0) !== 1 ? "s" : ""}`}
                icon={Target}
              />
              <StatCard
                label="Conversion"
                value={conversionRate != null ? `${conversionRate}%` : "—"}
                sub="interested → applied+"
                icon={TrendingUp}
              />
              <StatCard
                label="Avg Score"
                value={avgScore != null ? `${avgScore}%` : "—"}
                sub="tracked applications"
                icon={BarChart2}
              />
            </div>

            {/* Sankey: Tier → Status flow */}
            <div>
              <div className="section-label mb-3">application flow</div>
              <div className="stat-card border border-border bg-card p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">
                    Tier → Status Pipeline
                  </span>
                  <GitBranch size={12} className="text-muted-foreground" />
                </div>
                <SankeyDiagram applications={effectiveApplications} />
              </div>
            </div>

            {/* Score & Companies side by side */}
            {effectiveLoading ? (
              <div>
                <div className="section-label mb-3">job market</div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="stat-card border border-border bg-card p-5">
                    <ChartSkeleton rows={5} />
                  </div>
                  <div className="stat-card border border-border bg-card p-5">
                    <ChartSkeleton rows={6} />
                  </div>
                </div>
              </div>
            ) : effectiveAnalytics && effectiveAnalytics.total > 0 ? (
              <div>
                <div className="section-label mb-3">job market</div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="stat-card border border-border bg-card p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">
                        Score Distribution
                      </span>
                      <BarChart2
                        size={12}
                        className="text-muted-foreground"
                      />
                    </div>
                    <MiniBarChart
                      data={effectiveAnalytics.score_distribution.map((d) => ({
                        label: d.range,
                        count: d.count,
                      }))}
                      maxVal={Math.max(
                        ...effectiveAnalytics.score_distribution.map((d) => d.count),
                        1
                      )}
                    />
                  </div>
                  <div className="stat-card border border-border bg-card p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">
                        Top Companies
                      </span>
                      <BarChart2
                        size={12}
                        className="text-muted-foreground"
                      />
                    </div>
                    <MiniBarChart
                      data={effectiveAnalytics.top_companies
                        .slice(0, 8)
                        .map((d) => ({ label: d.company, count: d.count }))}
                      maxVal={Math.max(
                        ...effectiveAnalytics.top_companies.map((d) => d.count),
                        1
                      )}
                      color="var(--terminal-green-bright)"
                    />
                  </div>
                </div>
              </div>
            ) : null}

            {/* Tier breakdown + Sources */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="section-label mb-3">tier breakdown</div>
                <div className="stat-card border border-border bg-card p-5 space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">
                      Applications by Tier
                    </span>
                    <Layers size={12} className="text-muted-foreground" />
                  </div>
                  <TierBreakdown applications={effectiveApplications} />
                </div>
              </div>

              {effectiveAnalytics && effectiveAnalytics.sites.length > 0 && (
                <div>
                  <div className="section-label mb-3">sources</div>
                  <div className="stat-card border border-border bg-card p-5 space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">
                        Jobs by Source
                      </span>
                      <BarChart2
                        size={12}
                        className="text-muted-foreground"
                      />
                    </div>
                    <MiniBarChart
                      data={effectiveAnalytics.sites.map((s) => ({
                        label: s.site,
                        count: s.count,
                      }))}
                      maxVal={Math.max(
                        ...effectiveAnalytics.sites.map((s) => s.count),
                        1
                      )}
                      color="var(--chart-3)"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Pipeline status breakdown */}
            {effectiveStats && effectiveStats.total > 0 && (
              <div>
                <div className="section-label mb-3">pipeline</div>
                <div className="stat-card border border-border bg-card px-5 py-4 space-y-3">
                  {Object.entries(effectiveStats.by_status)
                    .filter(([, c]) => c > 0)
                    .sort((a, b) => b[1] - a[1])
                    .map(([status, count]) => {
                      const pct = (count / effectiveStats.total) * 100;
                      const color =
                        STATUS_COLORS[status] ?? "var(--border)";
                      return (
                        <div key={status} className="flex items-center gap-3">
                          <span className="text-xs text-muted-foreground w-24 shrink-0">
                            {status.replace("_", " ")}
                          </span>
                          <div className="flex-1 h-2 bg-muted overflow-hidden">
                            <div
                              className="h-full transition-all duration-500"
                              style={{
                                width: `${pct}%`,
                                background: color,
                              }}
                            />
                          </div>
                          <span className="text-xs text-muted-foreground tabular-nums w-8 text-right">
                            {count}
                          </span>
                          <span className="text-[10px] text-muted-foreground tabular-nums w-10 text-right">
                            {pct.toFixed(0)}%
                          </span>
                        </div>
                      );
                    })}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

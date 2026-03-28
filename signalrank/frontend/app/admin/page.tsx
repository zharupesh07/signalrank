"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Users, Activity, BarChart2, Play, Trash2, Shield, ShieldOff, CheckCircle, XCircle } from "lucide-react";

type AdminUser = {
  id: string;
  email: string;
  is_admin: boolean;
  created_at: string;
  last_login: string | null;
  onboarding_complete: boolean;
  run_count: number;
  last_run_status: string | null;
};

type AdminRun = {
  run_id: string;
  user_email: string;
  status: string;
  job_count: number | null;
  started_at: string | null;
  finished_at: string | null;
};

type Stats = {
  total_users: number;
  total_jobs: number;
  total_runs: number;
  total_applications: number;
};

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    success: "text-primary border-primary/30",
    done: "text-primary border-primary/30",
    failed: "text-destructive border-destructive/30",
    pending: "text-[var(--terminal-yellow)] border-[var(--terminal-yellow)]/30",
    scraping: "text-blue-400 border-blue-400/30",
    ranking: "text-blue-400 border-blue-400/30",
    cancelled: "text-muted-foreground border-border",
  };
  return (
    <span className={`text-[11px] border px-1.5 py-0.5 leading-none uppercase ${colors[status] ?? "text-muted-foreground border-border"}`}>
      {status}
    </span>
  );
}

export default function AdminPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const isAdmin = (session as { isAdmin?: boolean })?.isAdmin ?? false;
  const { toast } = useToast();

  const [tab, setTab] = useState<"users" | "runs">("users");
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [runs, setRuns] = useState<AdminRun[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (session && !isAdmin) {
      router.replace("/dashboard");
    }
  }, [session, isAdmin, router]);

  useEffect(() => {
    if (!token || !isAdmin) return;
    setLoading(true);
    Promise.all([
      api.admin.stats(token).then(setStats),
      api.admin.users(token).then(setUsers),
      api.admin.runs(token).then(setRuns),
    ])
      .catch(() => toast("Failed to load admin data", "error"))
      .finally(() => setLoading(false));
  }, [token, isAdmin]);

  async function toggleAdmin(userId: string, current: boolean) {
    await api.admin.updateUser(token, userId, { is_admin: !current });
    setUsers((prev) => prev.map((u) => (u.id === userId ? { ...u, is_admin: !current } : u)));
    toast(`Admin ${!current ? "granted" : "revoked"}`, "success");
  }

  async function deleteUser(userId: string, email: string) {
    if (!confirm(`Delete ${email} and all their data?`)) return;
    await api.admin.deleteUser(token, userId);
    setUsers((prev) => prev.filter((u) => u.id !== userId));
    toast(`Deleted ${email}`, "success");
  }

  async function triggerRun(userId: string) {
    const res = await api.admin.triggerRun(token, userId);
    toast(`Run queued for ${res.user_email}`, "success");
    const updated = await api.admin.runs(token);
    setRuns(updated);
  }

  if (!isAdmin) return null;

  return (
    <div className="pt-14 min-h-screen page-content">
      <div className="max-w-5xl mx-auto px-6 py-8 space-y-7">
        <div className="space-y-1">
          <div className="section-label">admin</div>
          <h1 className="text-xl font-bold text-foreground tracking-tight">System Administration</h1>
        </div>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-4 gap-3">
            {[
              { label: "Users", value: stats.total_users, icon: Users },
              { label: "Jobs", value: stats.total_jobs, icon: BarChart2 },
              { label: "Runs", value: stats.total_runs, icon: Activity },
              { label: "Applications", value: stats.total_applications, icon: CheckCircle },
            ].map(({ label, value, icon: Icon }) => (
              <div key={label} className="stat-card border border-border bg-card p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground uppercase tracking-[0.15em]">{label}</span>
                  <Icon size={12} className="text-muted-foreground" />
                </div>
                <div className="text-3xl font-bold tabular-nums leading-none text-foreground">{value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-1 border-b border-border">
          {(["users", "runs"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-xs uppercase tracking-widest transition-colors ${
                tab === t ? "text-primary border-b-2 border-primary" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="text-center py-12 text-muted-foreground text-sm">Loading...</div>
        ) : tab === "users" ? (
          <div className="space-y-px">
            <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 px-4 py-2 text-[11px] text-muted-foreground uppercase tracking-widest">
              <span>Email</span>
              <span>Onboarding</span>
              <span>Runs</span>
              <span>Last Login</span>
              <span>Role</span>
              <span>Actions</span>
            </div>
            {users.map((u) => (
              <div
                key={u.id}
                className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_auto] gap-3 items-center px-4 py-3 bg-card border border-border"
              >
                <span className="text-sm text-foreground truncate">{u.email}</span>
                <span>
                  {u.onboarding_complete ? (
                    <CheckCircle size={14} className="text-primary" />
                  ) : (
                    <XCircle size={14} className="text-[var(--terminal-yellow)]" />
                  )}
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-sm tabular-nums">{u.run_count}</span>
                  {u.last_run_status && <StatusBadge status={u.last_run_status} />}
                </div>
                <span className="text-xs text-muted-foreground">
                  {u.last_login ? new Date(u.last_login).toLocaleDateString([], { month: "short", day: "numeric" }) : "Never"}
                </span>
                <span>
                  {u.is_admin && (
                    <span className="text-[11px] text-primary border border-primary/30 px-1.5 py-0.5 leading-none uppercase">admin</span>
                  )}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => triggerRun(u.id)}
                    className="p-1.5 text-muted-foreground hover:text-primary transition-colors"
                    title="Trigger run"
                  >
                    <Play size={12} />
                  </button>
                  <button
                    onClick={() => toggleAdmin(u.id, u.is_admin)}
                    className="p-1.5 text-muted-foreground hover:text-[var(--terminal-yellow)] transition-colors"
                    title={u.is_admin ? "Revoke admin" : "Grant admin"}
                  >
                    {u.is_admin ? <ShieldOff size={12} /> : <Shield size={12} />}
                  </button>
                  <button
                    onClick={() => deleteUser(u.id, u.email)}
                    className="p-1.5 text-muted-foreground hover:text-destructive transition-colors"
                    title="Delete user"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-px">
            <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr] gap-3 px-4 py-2 text-[11px] text-muted-foreground uppercase tracking-widest">
              <span>User</span>
              <span>Status</span>
              <span>Jobs</span>
              <span>Started</span>
              <span>Finished</span>
            </div>
            {runs.map((r) => (
              <div
                key={r.run_id}
                className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr] gap-3 items-center px-4 py-3 bg-card border border-border"
              >
                <span className="text-sm text-foreground truncate">{r.user_email}</span>
                <StatusBadge status={r.status} />
                <span className="text-sm tabular-nums">{r.job_count ?? "—"}</span>
                <span className="text-xs text-muted-foreground">
                  {r.started_at ? new Date(r.started_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                </span>
                <span className="text-xs text-muted-foreground">
                  {r.finished_at ? new Date(r.finished_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                </span>
              </div>
            ))}
            {runs.length === 0 && (
              <div className="text-center py-8 text-muted-foreground text-sm">No runs yet</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

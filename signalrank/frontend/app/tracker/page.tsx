"use client";

import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import type { Application, ApplicationStatus } from "@/types";
import { useToast } from "@/components/toast";
import { Trash2 } from "lucide-react";

const STATUSES: ApplicationStatus[] = [
  "interested",
  "applied",
  "phone_screen",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
];

const STATUS_STYLE: Record<ApplicationStatus, { dot: string; label: string; border: string }> = {
  interested:   { dot: "bg-[#71717a]",  label: "text-[#a1a1aa]", border: "border-[#3f3f46]" },
  applied:      { dot: "bg-[#22c55e]",  label: "text-[#22c55e]", border: "border-[#22c55e]/40" },
  phone_screen: { dot: "bg-[#a3e635]",  label: "text-[#a3e635]", border: "border-[#a3e635]/40" },
  interview:    { dot: "bg-[#22c55e]",  label: "text-[#22c55e]", border: "border-[#22c55e]/60" },
  offer:        { dot: "bg-[#facc15]",  label: "text-[#facc15]", border: "border-[#facc15]/40" },
  rejected:     { dot: "bg-[#ef4444]",  label: "text-[#ef4444]", border: "border-[#ef4444]/30" },
  withdrawn:    { dot: "bg-[#52525b]",  label: "text-[#52525b]", border: "border-[#3f3f46]" },
};

export default function TrackerPage() {
  const { data: session } = useSession();
  const token = (session as { accessToken?: string })?.accessToken ?? "";
  const { toast } = useToast();

  const [applications, setApplications] = useState<Application[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    api.applications.list(token).then(setApplications);
  }, [token]);

  async function updateStatus(id: string, status: ApplicationStatus) {
    const app = applications.find((a) => a.id === id);
    const updated = await api.applications.update(token, id, { status });
    setApplications((apps) => apps.map((a) => (a.id === id ? { ...a, ...updated } : a)));
    if (app) toast(`${app.title} → ${status.replace("_", " ")}`, "success");
  }

  async function deleteApp(id: string) {
    if (confirmDelete !== id) {
      setConfirmDelete(id);
      setTimeout(() => setConfirmDelete(null), 3000);
      return;
    }
    const app = applications.find((a) => a.id === id);
    await api.applications.delete(token, id);
    setApplications((apps) => apps.filter((a) => a.id !== id));
    if (app) toast(`Removed: ${app.title}`, "info");
    setConfirmDelete(null);
  }

  const byStatus = STATUSES.reduce(
    (acc, s) => ({ ...acc, [s]: applications.filter((a) => a.status === s) }),
    {} as Record<ApplicationStatus, Application[]>
  );

  const visibleStatuses = STATUSES.filter(
    (s) => byStatus[s].length > 0 || ["interested", "applied", "interview"].includes(s)
  );

  return (
    <div className="pt-12 min-h-screen">
      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        <div>
          <div className="text-[10px] text-[#52525b] uppercase tracking-widest mb-1">// APPLICATION TRACKER</div>
          <div className="flex items-baseline gap-3">
            <h1 className="text-lg font-bold text-[#e4e4e7]">Tracker</h1>
            <span className="text-[#22c55e] text-sm tabular-nums">{applications.length} total</span>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
          {visibleStatuses.map((status) => {
            const style = STATUS_STYLE[status];
            const apps = byStatus[status];
            return (
              <div key={status} className="space-y-2">
                <div className="flex items-center gap-2 pb-1 border-b border-[#3f3f46]">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${style.dot}`} />
                  <span className={`text-[10px] uppercase tracking-wider ${style.label}`}>
                    {status.replace("_", " ")}
                  </span>
                  <span className="text-[10px] text-[#52525b] ml-auto tabular-nums">
                    {apps.length}
                  </span>
                </div>

                {apps.length === 0 ? (
                  <div className="border border-dashed border-[#27272a] p-3 text-center">
                    <span className="text-[10px] text-[#3f3f46]">empty</span>
                  </div>
                ) : (
                  apps.map((app) => (
                    <div
                      key={app.id}
                      className={`border bg-[#18181b] p-3 space-y-2 ${style.border}`}
                    >
                      <div>
                        <div className="text-xs text-[#e4e4e7] truncate">{app.title}</div>
                        <div className="text-[10px] text-[#71717a] truncate">{app.company}</div>
                      </div>
                      <select
                        value={app.status}
                        onChange={(e) => updateStatus(app.id, e.target.value as ApplicationStatus)}
                        className="w-full text-[10px] bg-[#0a0a0a] border border-[#3f3f46] text-[#a1a1aa] px-1.5 py-1 focus:border-[#22c55e] focus:outline-none"
                      >
                        {STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {s.replace("_", " ")}
                          </option>
                        ))}
                      </select>
                      <button
                        onClick={() => deleteApp(app.id)}
                        className={`flex items-center gap-1 text-[10px] transition-colors ${
                          confirmDelete === app.id
                            ? "text-[#ef4444]"
                            : "text-[#52525b] hover:text-[#ef4444]"
                        }`}
                      >
                        <Trash2 size={10} />
                        {confirmDelete === app.id ? "Confirm?" : "Remove"}
                      </button>
                    </div>
                  ))
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

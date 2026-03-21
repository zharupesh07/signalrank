"use client";

import { useSession, signOut } from "next-auth/react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { LogOut } from "lucide-react";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/tracker", label: "Tracker" },
];

export default function Navbar() {
  const { data: session } = useSession();
  const pathname = usePathname();

  if (!session) return null;

  const email = (session.user as { email?: string })?.email ?? "";

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 h-12 bg-[#0a0a0a] border-b border-[#3f3f46] flex items-center px-6 gap-8">
      <Link
        href="/dashboard"
        className="text-[#22c55e] font-bold text-sm tracking-widest text-glow-green shrink-0"
      >
        SIGNAL<span className="text-[#a3e635]">RANK</span>
      </Link>

      <div className="flex items-center gap-1 flex-1">
        {NAV_LINKS.map(({ href, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`px-3 py-1 text-xs tracking-wider transition-colors ${
                active
                  ? "text-[#22c55e] border-b border-[#22c55e]"
                  : "text-[#71717a] hover:text-[#a1a1aa]"
              }`}
            >
              {label.toUpperCase()}
            </Link>
          );
        })}
      </div>

      <div className="flex items-center gap-4 shrink-0">
        <span className="text-[#52525b] text-xs hidden sm:block truncate max-w-[180px]">
          {email}
        </span>
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="flex items-center gap-1.5 text-xs text-[#71717a] hover:text-[#ef4444] transition-colors"
        >
          <LogOut size={12} />
          <span className="hidden sm:inline">LOGOUT</span>
        </button>
      </div>
    </nav>
  );
}

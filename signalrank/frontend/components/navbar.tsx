"use client";

import { useState } from "react";
import { useSession, signOut } from "next-auth/react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { LogOut, Terminal, Sun, Moon } from "lucide-react";
import { useTheme } from "./theme-provider";
import SettingsPanel from "./settings-panel";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/tracker", label: "Tracker" },
  { href: "/runs", label: "Runs" },
];

export default function Navbar() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const [settingsPanelOpen, setSettingsPanelOpen] = useState(false);

  if (!session) return null;

  const email = (session.user as { email?: string })?.email ?? "";

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 h-13 bg-[#080808]/95 backdrop-blur-sm border-b border-[#2a2a2e] nav-glow flex items-center px-6 gap-8">
      {/* Logo */}
      <Link href="/dashboard" className="flex items-center gap-2 shrink-0 group">
        <Terminal size={14} className="text-[#22c55e] group-hover:text-[#a3e635] transition-colors" />
        <span className="text-[#22c55e] font-bold text-sm tracking-[0.2em] text-glow-dim group-hover:text-glow-green transition-all">
          SIGNAL<span className="text-[#a3e635]">RANK</span>
        </span>
      </Link>

      {/* Separator */}
      <div className="w-px h-4 bg-[#2a2a2e]" />

      {/* Nav links */}
      <div className="flex items-center gap-0.5 flex-1">
        {NAV_LINKS.map(({ href, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`relative px-3 py-2 text-xs tracking-widest transition-all duration-150 ${
                active
                  ? "text-[#22c55e]"
                  : "text-[#52525b] hover:text-[#a1a1aa]"
              }`}
            >
              {label.toUpperCase()}
              {active && (
                <span className="absolute bottom-0 left-2 right-2 h-px bg-[#22c55e] shadow-[0_0_6px_rgba(34,197,94,0.8)]" />
              )}
            </Link>
          );
        })}
      </div>

      {/* Right side */}
      <div className="flex items-center gap-5 shrink-0">
        <button
          onClick={toggleTheme}
          className="text-[#3f3f46] hover:text-[var(--fg)] transition-colors"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
        </button>
        <div className="hidden sm:flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#22c55e] pulse-dot" />
          <button
            onClick={() => setSettingsPanelOpen(true)}
            className="text-[#3f3f46] text-xs truncate max-w-[160px] cursor-pointer hover:text-[var(--fg)] transition-colors"
          >
            {email}
          </button>
        </div>
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="flex items-center gap-1.5 text-xs text-[#3f3f46] hover:text-[#ef4444] transition-colors group"
        >
          <LogOut size={11} className="group-hover:rotate-12 transition-transform" />
          <span className="hidden sm:inline tracking-wider">LOGOUT</span>
        </button>
      </div>
    </nav>
    <SettingsPanel isOpen={settingsPanelOpen} onClose={() => setSettingsPanelOpen(false)} />
  );
}

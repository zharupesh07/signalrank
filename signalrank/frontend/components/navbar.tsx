"use client";

import { useSession, signOut } from "next-auth/react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { LogOut, Terminal, Sun, Moon, Code2, Shield } from "lucide-react";
import { useTheme } from "./theme-provider";
import { useDevMode } from "./dev-mode-provider";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/jobs", label: "Jobs" },
  { href: "/tracker", label: "Tracker" },
  { href: "/analytics", label: "Analytics" },
  { href: "/runs", label: "Runs" },
  { href: "/settings", label: "Settings" },
];

export default function Navbar() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const { isDevMode, handleLogoClick, openDevPanel } = useDevMode();

  if (!session) return null;

  const email = (session.user as { email?: string })?.email ?? "";
  const isAdmin = (session as { isAdmin?: boolean })?.isAdmin ?? false;

  const links = isAdmin
    ? [...NAV_LINKS, { href: "/admin", label: "Admin" }]
    : NAV_LINKS;

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 h-13 bg-background/95 backdrop-blur-sm border-b border-border nav-glow flex items-center px-6 gap-8">
      {/* Logo */}
      <Link href="/dashboard" onClick={handleLogoClick} className="flex items-center gap-2 shrink-0 group relative">
        <Terminal size={14} className="text-primary group-hover:text-[var(--terminal-green-bright)] transition-colors" />
        <span className="text-primary font-bold text-sm tracking-[0.2em] text-glow-dim group-hover:text-glow-green transition-all">
          SIGNAL<span className="text-[var(--terminal-green-bright)]">RANK</span>
        </span>
        {isDevMode && (
          <span className="absolute -top-0.5 -right-1.5 w-1.5 h-1.5 rounded-full bg-terminal-yellow pulse-dot" />
        )}
      </Link>

      {/* Separator */}
      <div className="w-px h-4 bg-border" />

      {/* Nav links */}
      <div className="flex items-center gap-0.5 flex-1">
        {links.map(({ href, label }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`relative px-3 py-2 text-xs tracking-widest transition-all duration-150 ${
                active
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {label.toUpperCase()}
              {active && (
                <span className="absolute bottom-0 left-2 right-2 h-px bg-primary shadow-[0_0_6px_rgba(34,197,94,0.8)]" />
              )}
            </Link>
          );
        })}
      </div>

      {/* Right side */}
      <div className="flex items-center gap-5 shrink-0">
        {isDevMode && (
          <button
            onClick={openDevPanel}
            className="flex items-center gap-1.5 text-xs text-terminal-yellow hover:text-terminal-green-bright transition-colors"
            title="Open Dev Console"
          >
            <Code2 size={12} />
            <span className="hidden sm:inline tracking-wider uppercase">Dev</span>
          </button>
        )}
        <button
          onClick={toggleTheme}
          className="text-muted-foreground hover:text-foreground transition-colors"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
        </button>
        <div className="hidden sm:flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-primary pulse-dot" />
          <Link
            href="/settings"
            className="text-muted-foreground text-xs truncate max-w-[160px] hover:text-foreground transition-colors"
          >
            {email}
          </Link>
        </div>
        <button
          onClick={() => signOut({ callbackUrl: "/login" })}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-destructive transition-colors group"
        >
          <LogOut size={11} className="group-hover:rotate-12 transition-transform" />
          <span className="hidden sm:inline tracking-wider">LOGOUT</span>
        </button>
      </div>
    </nav>
  );
}

"use client";

import { useState } from "react";
import { useSession, signOut } from "next-auth/react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { LogOut, Terminal, Sun, Moon, Menu, X } from "lucide-react";
import { useTheme } from "./theme-provider";

const NAV_LINKS = [
  { href: "/dashboard", label: "Matches" },
  { href: "/tracker", label: "Tracker" },
  { href: "/settings", label: "Resume" },
];

export default function Navbar() {
  const { data: session } = useSession();
  const pathname = usePathname();
  const { theme, toggleTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);

  if (!session) return null;

  const email = (session.user as { email?: string })?.email ?? "";
  const isAdmin = (session as { isAdmin?: boolean })?.isAdmin ?? false;
  const isDesktop = process.env.NEXT_PUBLIC_SIGNALRANK_MODE === "desktop";

  const links = isAdmin && !isDesktop
    ? [...NAV_LINKS, { href: "/admin", label: "Admin" }]
    : NAV_LINKS;

  return (
    <>
      <nav className="fixed top-0 left-0 right-0 z-50 h-13 bg-background/95 backdrop-blur-sm border-b border-border nav-glow flex items-center px-6 gap-8">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 shrink-0 group relative">
          <Terminal size={14} className="text-primary group-hover:text-[var(--terminal-green-bright)] transition-colors" />
          <span className="text-primary font-bold text-sm tracking-[0.2em] text-glow-dim group-hover:text-glow-green transition-all">
            SIGNAL<span className="text-[var(--terminal-green-bright)]">RANK</span>
          </span>
        </Link>

        {/* Separator */}
        <div className="w-px h-4 bg-border hidden sm:block" />

        {/* Nav links — desktop */}
        <div className="hidden sm:flex items-center gap-0.5 flex-1">
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

        {/* Spacer on mobile */}
        <div className="flex-1 sm:hidden" />

        {/* Right side */}
        <div className="flex items-center gap-5 shrink-0">
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
          {!isDesktop && (
            <button
              onClick={() => signOut({ callbackUrl: "/login" })}
              className="hidden sm:flex items-center gap-1.5 text-xs text-muted-foreground hover:text-destructive transition-colors group"
            >
              <LogOut size={11} className="group-hover:rotate-12 transition-transform" />
              <span className="tracking-wider">LOGOUT</span>
            </button>
          )}
          {/* Hamburger — mobile only */}
          <button
            onClick={() => setMobileOpen((v) => !v)}
            className="sm:hidden text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Toggle menu"
          >
            {mobileOpen ? <X size={16} /> : <Menu size={16} />}
          </button>
        </div>
      </nav>

      {/* Mobile dropdown menu */}
      {mobileOpen && (
        <div className="fixed top-13 left-0 right-0 z-40 bg-background/98 border-b border-border sm:hidden">
          <div className="flex flex-col px-6 py-3 gap-1">
            {links.map(({ href, label }) => {
              const active = pathname === href || pathname.startsWith(href + "/");
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={() => setMobileOpen(false)}
                  className={`px-3 py-2.5 text-xs tracking-widest transition-colors ${
                    active ? "text-primary" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label.toUpperCase()}
                </Link>
              );
            })}
            <div className="border-t border-border mt-2 pt-3 flex items-center justify-between">
              <span className="text-xs text-muted-foreground truncate max-w-[200px]">{email}</span>
              {!isDesktop && (
                <button
                  onClick={() => signOut({ callbackUrl: "/login" })}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-destructive transition-colors"
                >
                  <LogOut size={11} />
                  <span className="tracking-wider">LOGOUT</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

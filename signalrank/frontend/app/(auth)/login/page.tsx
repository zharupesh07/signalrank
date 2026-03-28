"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await signIn("credentials", { email, password, redirect: false });
      if (res?.error) {
        setError("Invalid credentials");
      } else {
        router.push("/dashboard");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#080808] scanlines px-4">
      <div className="w-full max-w-sm space-y-8">
        <div className="text-center space-y-1">
          <div className="text-3xl font-bold text-[#22c55e] text-glow-green tracking-widest">
            SIGNAL<span className="text-[#a3e635]">RANK</span>
          </div>
          <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
            Job Intelligence Terminal
          </div>
        </div>

        <div className="border border-[#2a2a2e] bg-[#111113] p-6 space-y-5 stat-card">
          <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
            // AUTHENTICATE
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[10px] text-[#71717a] uppercase tracking-wider">Email</label>
              <div className="flex items-center border border-[#2a2a2e] bg-[#080808] focus-within:border-[#22c55e] focus-within:shadow-[0_0_0_1px_rgba(34,197,94,0.15)] transition-colors">
                <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                  placeholder="user@example.com"
                  suppressHydrationWarning
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] text-[#71717a] uppercase tracking-wider">Password</label>
              <div className="flex items-center border border-[#2a2a2e] bg-[#080808] focus-within:border-[#22c55e] focus-within:shadow-[0_0_0_1px_rgba(34,197,94,0.15)] transition-colors">
                <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                  placeholder="••••••••"
                  suppressHydrationWarning
                />
              </div>
            </div>

            {error && (
              <div className="text-[11px] text-[#ef4444] flex items-center gap-2">
                <span>&gt;</span>
                <span>ERR: {error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 text-xs font-bold uppercase tracking-widest bg-[#22c55e] text-[#0a0a0a] hover:bg-[#a3e635] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Authenticating..." : "Sign In"}
            </button>
          </form>

          <div className="text-[10px] text-[#52525b] text-center">
            No account?{" "}
            <a href="/signup" className="text-[#22c55e] hover:text-[#a3e635] transition-colors">
              Register
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { signIn } from "next-auth/react";

export default function SignupPage() {
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
      await api.auth.register(email, password);
      await signIn("credentials", { email, password, redirect: false });
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] scanlines px-4">
      <div className="w-full max-w-sm space-y-8">
        <div className="text-center space-y-1">
          <div className="text-3xl font-bold text-[#22c55e] text-glow-green tracking-widest">
            SIGNAL<span className="text-[#a3e635]">RANK</span>
          </div>
          <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
            Job Intelligence Terminal
          </div>
        </div>

        <div className="border border-[#3f3f46] bg-[#18181b] p-6 space-y-5">
          <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
            // NEW USER REGISTRATION
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-[10px] text-[#71717a] uppercase tracking-wider">Email</label>
              <div className="flex items-center border border-[#3f3f46] bg-[#0a0a0a] focus-within:border-[#22c55e] transition-colors">
                <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                  placeholder="user@example.com"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] text-[#71717a] uppercase tracking-wider">Password</label>
              <div className="flex items-center border border-[#3f3f46] bg-[#0a0a0a] focus-within:border-[#22c55e] transition-colors">
                <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={6}
                  className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                  placeholder="min. 6 characters"
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
              {loading ? "Creating account..." : "Create Account"}
            </button>
          </form>

          <div className="text-[10px] text-[#52525b] text-center">
            Already registered?{" "}
            <a href="/login" className="text-[#22c55e] hover:text-[#a3e635] transition-colors">
              Sign in
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

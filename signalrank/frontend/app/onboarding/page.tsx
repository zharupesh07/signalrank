"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { api } from "@/lib/api";
import { Upload } from "lucide-react";

type Question = {
  id: string;
  text: string;
  type: "text" | "multiselect";
  options?: string[];
};

export default function OnboardingPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const token = (session as { accessToken?: string })?.accessToken ?? "";

  const [step, setStep] = useState<"upload" | "questions">("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const res = await api.onboarding.uploadResume(token, file);
      setQuestions(res.questions as Question[]);
      setStep("questions");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleFinish(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      for (const [qid, answer] of Object.entries(answers)) {
        if (answer.trim()) await api.onboarding.refine(token, qid, answer);
      }
      await api.onboarding.refine(token, "onboarding_complete", "true");
      await api.runs.trigger(token);
      router.push("/dashboard");
    } finally {
      setSubmitting(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0a0a0a] px-4">
      <div className="w-full max-w-lg space-y-6">

        <div className="text-center space-y-1">
          <div className="text-2xl font-bold text-[#22c55e] text-glow-green tracking-widest">
            SIGNAL<span className="text-[#a3e635]">RANK</span>
          </div>
          <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
            Setup Wizard
          </div>
        </div>

        <div className="flex items-center gap-0">
          {["UPLOAD RESUME", "PREFERENCES"].map((label, i) => {
            const currentStep = step === "upload" ? 0 : 1;
            const active = i === currentStep;
            const done = i < currentStep;
            return (
              <div key={i} className="flex items-center flex-1">
                <div className={`flex items-center gap-2 text-[10px] uppercase tracking-wider ${
                  active ? "text-[#22c55e]" : done ? "text-[#52525b]" : "text-[#3f3f46]"
                }`}>
                  <span className={`w-5 h-5 flex items-center justify-center border text-[9px] font-bold ${
                    active ? "border-[#22c55e] text-[#22c55e]" : done ? "border-[#52525b] text-[#52525b]" : "border-[#3f3f46] text-[#3f3f46]"
                  }`}>
                    {done ? "✓" : i + 1}
                  </span>
                  {label}
                </div>
                {i < 1 && <div className={`flex-1 h-px mx-3 ${done ? "bg-[#52525b]" : "bg-[#27272a]"}`} />}
              </div>
            );
          })}
        </div>

        <div className="border border-[#3f3f46] bg-[#18181b] p-6">
          {step === "upload" ? (
            <form onSubmit={handleUpload} className="space-y-5">
              <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
                // [1/2] UPLOAD RESUME
              </div>

              <label
                className={`block border-2 border-dashed p-8 text-center cursor-pointer transition-colors ${
                  dragging
                    ? "border-[#22c55e] bg-[#22c55e]/5"
                    : file
                    ? "border-[#22c55e]/60 bg-[#22c55e]/5"
                    : "border-[#3f3f46] hover:border-[#52525b]"
                }`}
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
              >
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="hidden"
                />
                <div className="space-y-2">
                  <Upload size={20} className={file ? "text-[#22c55e] mx-auto" : "text-[#52525b] mx-auto"} />
                  {file ? (
                    <div>
                      <div className="text-xs text-[#22c55e]">{file.name}</div>
                      <div className="text-[10px] text-[#52525b]">
                        {(file.size / 1024).toFixed(0)} KB
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="text-xs text-[#71717a]">Drop resume here or click to browse</div>
                      <div className="text-[10px] text-[#52525b] mt-1">PDF · DOCX · TXT</div>
                    </div>
                  )}
                </div>
              </label>

              {error && (
                <div className="text-[11px] text-[#ef4444]">&gt; ERR: {error}</div>
              )}

              <button
                type="submit"
                disabled={uploading || !file}
                className="w-full py-2.5 text-xs font-bold uppercase tracking-widest bg-[#22c55e] text-[#0a0a0a] hover:bg-[#a3e635] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {uploading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="inline-block w-1 h-3 bg-[#0a0a0a] animate-pulse" />
                    Parsing
                    <span className="tracking-widest">...</span>
                  </span>
                ) : "Parse Resume"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleFinish} className="space-y-5">
              <div className="text-[10px] text-[#52525b] uppercase tracking-widest">
                // [2/2] PREFERENCES
              </div>

              <div className="space-y-4">
                {questions.map((q: Question) => (
                  <div key={q.id} className="space-y-1.5">
                    <label className="text-[10px] text-[#71717a] uppercase tracking-wider">
                      {q.text}
                    </label>
                    <div className="flex items-center border border-[#3f3f46] bg-[#0a0a0a] focus-within:border-[#22c55e] transition-colors">
                      <span className="text-[#22c55e] text-xs pl-3 select-none">&gt;</span>
                      <input
                        value={answers[q.id] ?? ""}
                        onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                        className="flex-1 bg-transparent px-2 py-2.5 text-sm text-[#e4e4e7] outline-none placeholder:text-[#3f3f46]"
                        placeholder="Your answer"
                      />
                    </div>
                  </div>
                ))}
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 text-xs font-bold uppercase tracking-widest bg-[#22c55e] text-[#0a0a0a] hover:bg-[#a3e635] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {submitting ? "Setting up..." : "Finish Setup"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

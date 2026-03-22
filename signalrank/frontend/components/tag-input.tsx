"use client";

import { KeyboardEvent, useState } from "react";

interface TagInputProps {
  label: string;
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

export function TagInput({ label, value, onChange, placeholder }: TagInputProps) {
  const [input, setInput] = useState("");

  function addTag(raw: string) {
    const tag = raw.trim();
    if (!tag || value.includes(tag)) return;
    onChange([...value, tag]);
  }

  function removeTag(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
      setInput("");
    } else if (e.key === "Backspace" && input === "") {
      removeTag(value.length - 1);
    }
  }

  function handleChange(raw: string) {
    if (raw.endsWith(",")) {
      addTag(raw.slice(0, -1));
      setInput("");
    } else {
      setInput(raw);
    }
  }

  return (
    <div>
      <label className="block text-xs text-[var(--fg-muted)] mb-1">{label}</label>
      <div className="bg-[var(--bg-input)] border border-[var(--border)] rounded-md p-2 flex flex-wrap gap-1.5">
        {value.map((tag, i) => (
          <span
            key={i}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--bg-input)] border border-[var(--border)] text-[var(--fg)] text-sm"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(i)}
              className="text-[var(--fg-muted)] hover:text-[var(--fg)] leading-none"
            >
              ×
            </button>
          </span>
        ))}
        <input
          type="text"
          value={input}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="flex-1 min-w-24 bg-transparent text-[var(--fg)] placeholder:text-[var(--fg-dim)] text-sm outline-none border-none"
        />
      </div>
    </div>
  );
}

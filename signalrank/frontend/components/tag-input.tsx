"use client";

import { KeyboardEvent, useRef, useState, useEffect } from "react";

interface TagInputProps {
  label: string;
  value: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
  suggestions?: string[];
}

export function TagInput({ label, value, onChange, placeholder, suggestions = [] }: TagInputProps) {
  const [input, setInput] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(-1);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const filtered = input.trim()
    ? suggestions.filter(
        (s) => s.toLowerCase().includes(input.toLowerCase()) && !value.includes(s)
      )
    : suggestions.filter((s) => !value.includes(s));

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function addTag(raw: string) {
    const tag = raw.trim();
    if (!tag || value.includes(tag)) return;
    onChange([...value, tag]);
  }

  function removeTag(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  function selectSuggestion(s: string) {
    addTag(s);
    setInput("");
    setShowSuggestions(false);
    setHighlightIndex(-1);
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (showSuggestions && filtered.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlightIndex((i) => (i + 1) % filtered.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlightIndex((i) => (i <= 0 ? filtered.length - 1 : i - 1));
        return;
      }
      if (e.key === "Enter" && highlightIndex >= 0) {
        e.preventDefault();
        selectSuggestion(filtered[highlightIndex]);
        return;
      }
    }
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
      setInput("");
      setShowSuggestions(false);
    } else if (e.key === "Backspace" && input === "") {
      removeTag(value.length - 1);
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  }

  function handleChange(raw: string) {
    if (raw.endsWith(",")) {
      addTag(raw.slice(0, -1));
      setInput("");
      setShowSuggestions(false);
      setHighlightIndex(-1);
    } else {
      setInput(raw);
      setHighlightIndex(-1);
      if (suggestions.length > 0) setShowSuggestions(true);
    }
  }

  return (
    <div ref={wrapperRef} className="relative">
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
              x
            </button>
          </span>
        ))}
        <input
          type="text"
          value={input}
          onChange={(e) => handleChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => suggestions.length > 0 && setShowSuggestions(true)}
          placeholder={value.length === 0 ? placeholder : ""}
          suppressHydrationWarning
          className="flex-1 min-w-24 bg-transparent text-[var(--fg)] placeholder:text-[var(--fg-dim)] text-sm outline-none border-none"
        />
      </div>
      {showSuggestions && filtered.length > 0 && (
        <div className="absolute z-50 left-0 right-0 mt-1 max-h-40 overflow-y-auto border border-border bg-card shadow-lg">
          {filtered.slice(0, 12).map((s, i) => (
            <button
              key={s}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => selectSuggestion(s)}
              className={`w-full text-left px-3 py-1.5 text-xs transition-colors ${
                i === highlightIndex
                  ? "bg-primary/15 text-primary"
                  : "text-foreground hover:bg-muted"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

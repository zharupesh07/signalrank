"use client";

import { useState } from "react";

interface ChipSelectProps {
  label: string;
  options: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
  allowCustom?: boolean;
  customPlaceholder?: string;
}

export function ChipSelect({
  label,
  options,
  selected,
  onChange,
  allowCustom = true,
  customPlaceholder = "Add custom...",
}: ChipSelectProps) {
  const [customInput, setCustomInput] = useState("");

  function toggle(option: string) {
    onChange(
      selected.includes(option)
        ? selected.filter((s) => s !== option)
        : [...selected, option]
    );
  }

  function addCustom() {
    const val = customInput.trim();
    if (val && !selected.includes(val)) {
      onChange([...selected, val]);
    }
    setCustomInput("");
  }

  function removeCustom(val: string) {
    onChange(selected.filter((s) => s !== val));
  }

  const customValues = selected.filter((s) => !options.includes(s));

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          {label}
        </label>
        {selected.length > 0 && (
          <div className="flex gap-1.5">
            <button
              type="button"
              onClick={() => onChange([])}
              className="text-[10px] text-muted-foreground hover:text-destructive transition-colors"
            >
              Clear
            </button>
            {selected.length < options.length && (
              <>
                <span className="text-[10px] text-border">|</span>
                <button
                  type="button"
                  onClick={() => onChange([...new Set([...selected, ...options])])}
                  className="text-[10px] text-muted-foreground hover:text-primary transition-colors"
                >
                  All
                </button>
              </>
            )}
          </div>
        )}
        {selected.length === 0 && (
          <button
            type="button"
            onClick={() => onChange([...options])}
            className="text-[10px] text-muted-foreground hover:text-primary transition-colors"
          >
            Select all
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const active = selected.includes(option);
          return (
            <button
              key={option}
              type="button"
              onClick={() => toggle(option)}
              className={`px-2.5 py-1 text-[11px] border transition-all duration-100 ${
                active
                  ? "border-primary text-primary bg-primary/10"
                  : "border-border text-muted-foreground hover:border-muted-foreground hover:text-foreground"
              }`}
            >
              {option}
            </button>
          );
        })}
        {customValues.map((val) => (
          <span
            key={val}
            className="flex items-center gap-1 px-2.5 py-1 text-[11px] border border-primary/60 text-primary bg-primary/5"
          >
            {val}
            <button
              type="button"
              onClick={() => removeCustom(val)}
              className="text-primary/50 hover:text-primary leading-none ml-0.5"
            >
              x
            </button>
          </span>
        ))}
      </div>
      {allowCustom && (
        <div className="mt-2 flex gap-1.5">
          <input
            type="text"
            value={customInput}
            onChange={(e) => setCustomInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustom();
              }
            }}
            placeholder={customPlaceholder}
            className="flex-1 bg-input border border-border px-2.5 py-1 text-[11px] text-foreground outline-none focus:border-primary transition-colors placeholder:text-muted-foreground"
          />
          {customInput.trim() && (
            <button
              type="button"
              onClick={addCustom}
              className="px-2 py-1 text-[11px] border border-primary/50 text-primary hover:bg-primary hover:text-background transition-colors"
            >
              Add
            </button>
          )}
        </div>
      )}
    </div>
  );
}

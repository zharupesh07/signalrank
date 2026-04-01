"use client";

import { KeyboardEvent, useRef, useState } from "react";
import { GripVertical, X } from "lucide-react";

interface DraggableTagListProps {
  title: string;
  tone: string;
  items: string[];
  onChange: (items: string[]) => void;
  onReceiveDrop: (item: string, sourceList: string) => void;
  listId: string;
  emptyLabel?: string;
  placeholder?: string;
}

let _dragSource: { listId: string; item: string } | null = null;

export function DraggableTagList({
  title,
  tone,
  items,
  onChange,
  onReceiveDrop,
  listId,
  emptyLabel = "None.",
  placeholder = "Type and press Enter to add…",
}: DraggableTagListProps) {
  const [input, setInput] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function addItem(raw: string) {
    const val = raw.trim();
    if (!val || items.includes(val)) return;
    onChange([...items, val]);
    setInput("");
  }

  function removeItem(item: string) {
    onChange(items.filter((i) => i !== item));
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addItem(input);
    } else if (e.key === "Backspace" && input === "") {
      onChange(items.slice(0, -1));
    }
  }

  function handleDragStart(item: string) {
    _dragSource = { listId, item };
  }

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(true);
  }

  function handleDragLeave() {
    setDragOver(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (!_dragSource || _dragSource.listId === listId) return;
    const { item, listId: sourceId } = _dragSource;
    _dragSource = null;
    if (items.includes(item)) return;
    onReceiveDrop(item, sourceId);
    onChange([...items, item]);
  }

  return (
    <div
      className={`space-y-2 border bg-background/40 p-4 transition-colors ${
        dragOver ? "border-primary/60 bg-primary/5" : "border-border"
      }`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex items-center justify-between">
        <div className={`text-[10px] uppercase tracking-[0.18em] ${tone}`}>{title}</div>
        <div className="text-[10px] tabular-nums text-muted-foreground">{items.length}</div>
      </div>

      <div className="flex flex-wrap gap-1.5 min-h-[2rem]">
        {items.length === 0 && (
          <span className="text-[11px] text-muted-foreground italic">{emptyLabel}</span>
        )}
        {items.map((item) => (
          <span
            key={item}
            draggable
            onDragStart={() => handleDragStart(item)}
            className={`group flex cursor-grab items-center gap-1 border px-1.5 py-0.5 text-[11px] active:cursor-grabbing ${tone} border-current/20 bg-current/5 select-none`}
          >
            <GripVertical size={10} className="opacity-40 group-hover:opacity-70" />
            {item}
            <button
              type="button"
              onClick={() => removeItem(item)}
              className="ml-0.5 opacity-40 hover:opacity-100 transition-opacity"
            >
              <X size={10} />
            </button>
          </span>
        ))}
      </div>

      <div className="flex gap-1.5">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          className="flex-1 bg-transparent border border-border rounded px-2 py-1 text-[11px] text-foreground placeholder:text-muted-foreground/50 outline-none focus:border-primary/50"
        />
        <button
          type="button"
          onClick={() => addItem(input)}
          disabled={!input.trim()}
          className={`px-2 py-1 text-[11px] border border-current/30 transition-opacity ${tone} disabled:opacity-30`}
        >
          Add
        </button>
      </div>
    </div>
  );
}

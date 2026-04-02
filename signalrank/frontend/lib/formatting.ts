/**
 * Returns a CSS color variable string for a score percentage (0–100).
 */
export function scoreColor(pct: number): string {
  if (pct >= 75) return "var(--primary)";
  if (pct >= 60) return "var(--terminal-green-bright)";
  if (pct >= 45) return "var(--terminal-yellow)";
  return "var(--destructive)";
}

/**
 * Parses an API date string (with or without T separator) into a Date.
 * Returns null if the value is null/undefined/invalid.
 */
export function parseApiDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Returns a human-readable job age label and color for display.
 * Returns null if the date is missing or invalid.
 */
export function formatJobAge(
  value: string | null | undefined
): { label: string; color: string } | null {
  const postedAt = parseApiDate(value);
  if (!postedAt) return null;

  const days = Math.max(0, Math.floor((Date.now() - postedAt.getTime()) / 86400000));
  if (days === 0) return { label: "today", color: "var(--terminal-green-bright)" };
  if (days < 14) return { label: `${days}d`, color: "var(--terminal-green-bright)" };
  if (days < 60) return { label: `${Math.floor(days / 7)}w`, color: "var(--terminal-yellow)" };
  return { label: `${Math.floor(days / 30)}mo`, color: "var(--muted-foreground)" };
}

/**
 * Converts a stored regex penalty pattern to a human-readable display string.
 */
export function formatPenaltyPattern(pattern: string): string {
  return pattern
    .replace(/\\b/g, "")
    .replace(/\\s\+/g, " ")
    .replace(/\\/g, "")
    .trim();
}

/**
 * Returns elapsed time string ("14s", "2m 5s") from a start timestamp string.
 * Returns "—" if the date is malformed/invalid.
 */
export function formatElapsed(startedAt: string): string {
  const ms = Date.now() - new Date(startedAt).getTime();
  if (Number.isNaN(ms)) return "—";
  const secs = Math.floor(ms / 1000);
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

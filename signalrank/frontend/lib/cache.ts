const DEFAULT_TTL = 300_000; // 5 minutes

interface CacheEntry<T> {
  data: T;
  ts: number;
}

export function getCached<T>(key: string, ttl = DEFAULT_TTL): T | null {
  try {
    const raw = localStorage.getItem(`sr:${key}`);
    if (!raw) return null;
    const entry: CacheEntry<T> = JSON.parse(raw);
    if (Date.now() - entry.ts > ttl) {
      localStorage.removeItem(`sr:${key}`);
      return null;
    }
    return entry.data;
  } catch {
    return null;
  }
}

export function setCache<T>(key: string, data: T): void {
  try {
    const entry: CacheEntry<T> = { data, ts: Date.now() };
    localStorage.setItem(`sr:${key}`, JSON.stringify(entry));
  } catch {
    // localStorage full or unavailable — ignore
  }
}

export function clearCache(key: string): void {
  try {
    localStorage.removeItem(`sr:${key}`);
  } catch {
    // ignore
  }
}

export function swr<T>(
  key: string,
  fetcher: () => Promise<T>,
  setter: (data: T) => void,
  ttl = DEFAULT_TTL,
): Promise<void> {
  const cached = getCached<T>(key, ttl);
  if (cached) setter(cached);
  return fetcher().then((fresh) => {
    setter(fresh);
    setCache(key, fresh);
  }).catch(() => {});
}

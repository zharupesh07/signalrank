import ctypes
import gc
import logging
import resource
import sys

_LIBC = None
if sys.platform.startswith("linux"):
    try:
        _LIBC = ctypes.CDLL("libc.so.6")
        _LIBC.malloc_trim.argtypes = [ctypes.c_size_t]
        _LIBC.malloc_trim.restype = ctypes.c_int
    except Exception:
        _LIBC = None


def rss_mb() -> float | None:
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        kb = int(line.split()[1])
                        return round(kb / 1024, 1)
        except Exception:
            pass
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if usage <= 0:
            return None
        # Linux reports KB, macOS reports bytes.
        if usage > 10_000_000:
            return round(usage / (1024 * 1024), 1)
        return round(usage / 1024, 1)
    except Exception:
        return None


def log_rss(logger: logging.Logger, phase: str, **extra) -> None:
    rss = rss_mb()
    payload = {"phase": phase, **extra}
    if rss is None:
        logger.info("[MEM] phase=%s", phase, extra=payload)
        return
    payload["rss_mb"] = rss
    logger.info("[MEM] phase=%s rss_mb=%.1f", phase, rss, extra=payload)


def trim_process_memory() -> bool:
    gc.collect()
    if _LIBC is None:
        return False
    try:
        return bool(_LIBC.malloc_trim(0))
    except Exception:
        return False


def release_memory(logger: logging.Logger, phase: str, **extra) -> None:
    before = rss_mb()
    trimmed = trim_process_memory()
    after = rss_mb()
    payload = {"phase": phase, "trimmed": trimmed, **extra}
    if before is not None:
        payload["rss_mb_before"] = before
    if after is not None:
        payload["rss_mb_after"] = after
    if before is not None and after is not None:
        logger.info(
            "[MEM] phase=%s trim=%s rss_mb_before=%.1f rss_mb_after=%.1f",
            phase,
            "yes" if trimmed else "no",
            before,
            after,
            extra=payload,
        )
    else:
        logger.info("[MEM] phase=%s trim=%s", phase, "yes" if trimmed else "no", extra=payload)

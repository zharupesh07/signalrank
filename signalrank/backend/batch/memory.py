import logging
import os
import resource
import subprocess


def rss_mb() -> float | None:
    try:
        kb = int(
            subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
        )
        return round(kb / 1024, 1)
    except Exception:
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

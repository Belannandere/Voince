import logging
import time
from contextlib import contextmanager

logger = logging.getLogger("timing")


@contextmanager
def timer(label: str):
    """Measure a block's wall-clock time.

    Logs at INFO level via the standard logging system, so output goes to
    journald in production and to stdout locally. Uses perf_counter for
    monotonic timing (not affected by wall-clock adjustments).
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - start) * 1000
        logger.info("[timing] %s: %.0f ms", label, ms)
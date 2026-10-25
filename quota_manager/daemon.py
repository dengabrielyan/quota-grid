from __future__ import annotations

import logging
import signal
import sys
import threading

from .orchestrator import refresh
from .util import load_config, safe_error

LOG = logging.getLogger(__name__)


def run_daemon() -> int:
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    stop = threading.Event()

    def _stop(signum: int, frame: object) -> None:
        LOG.info("received signal %s, stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    LOG.info("Quota Grid collector started")
    while not stop.is_set():
        try:
            refresh(notify=True)
        except Exception as exc:
            LOG.error("refresh loop failed: %s", safe_error(exc))
        interval = int(load_config()["refresh_interval_seconds"])
        stop.wait(interval)
    LOG.info("Quota Grid collector stopped")
    return 0

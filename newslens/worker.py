"""The background worker: `uv run python -m newslens.worker`.

Milestone 1: the worker only checks that it can reach TypeDB and reports how many analysis
runs are waiting. It does not claim or change any run. Retrieval and analysis are added in
Milestone 2.
"""

import logging
import signal
import sys
import threading

from newslens import store
from newslens.db import connect
from newslens.settings import ConfigError, load_settings

log = logging.getLogger("newslens.worker")
POLL_SECONDS = 30


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as error:
        print(error, file=sys.stderr)
        sys.exit(2)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    db, driver = settings.typedb_database, None
    log.info("worker started; analysis is not implemented yet (Milestone 2), runs stay queued")
    while not stop.is_set():
        try:
            driver = driver or connect(settings)
            if driver.databases.contains(db):
                log.info("%d analysis run(s) queued", store.count_queued_runs(driver, db))
            else:
                log.info("database %s not created yet (the API creates it on first use)", db)
        except Exception as error:
            log.warning("TypeDB unavailable: %s", type(error).__name__)
            if driver is not None:
                driver.close()
            driver = None
        stop.wait(POLL_SECONDS)
    if driver is not None:
        driver.close()
    log.info("worker stopped")


if __name__ == "__main__":
    main()

"""The background worker: `uv run python -m newslens.worker`.

Every few seconds: mark abandoned runs as failed, then claim the oldest queued run and run it
(retrieve -> extract -> claims). One run at a time.
"""

import logging
import signal
import sys
import threading
from pathlib import Path

from newslens import jobs, pipeline, store
from newslens.db import connect
from newslens.ingest.http import FetchConfig, Fetcher
from newslens.llm import provider_from_settings
from newslens.migrations import ensure_database
from newslens.settings import ConfigError, load_settings

log = logging.getLogger("newslens.worker")
POLL_SECONDS = 3


def work_once(driver, db, fetcher, model):
    """Recover abandoned runs, then run at most one queued run. Returns the run id or None."""
    for run_id in jobs.recover_abandoned(driver, db):
        log.warning("run %s was abandoned; marked failed", run_id)
    run_id = jobs.claim_next(driver, db)
    if run_id:
        log.info("run %s: started", run_id)
        outcome = pipeline.run_analysis(driver, db, run_id, fetcher, model)
        log.info("run %s: %s", run_id, outcome)
    return run_id


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

    db, driver, model = settings.typedb_database, None, None
    fetcher = Fetcher(FetchConfig(lock_dir=Path(settings.fetch_lock_dir)))
    log.info("worker started; model provider: %s", settings.newslens_model_provider)
    while not stop.is_set():
        try:
            if driver is None:
                driver = connect(settings)
                ensure_database(driver, db)
                store.ensure_methodology(driver, db)
                model = provider_from_settings(settings, driver, db)
            if work_once(driver, db, fetcher, model):
                continue                 # look for the next run straight away
        except Exception as error:
            log.warning("worker problem: %s", type(error).__name__)
            if driver is not None:
                driver.close()
            driver = None
        stop.wait(POLL_SECONDS)
    fetcher.close()
    if driver is not None:
        driver.close()
    log.info("worker stopped")


if __name__ == "__main__":
    main()

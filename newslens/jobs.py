"""Background jobs: analysis runs are the queue, kept in TypeDB (no other store).

Claiming: a worker changes a run from "queued" to "running" and sets a lease (a time by which
it must finish or renew). Two workers claiming the same run conflict in TypeDB; only one
commit succeeds, and the other moves on.

Recovery: a "running" run whose lease has passed was abandoned (the worker crashed or was
stopped). It is marked failed, with the reason, and is NOT re-run automatically: a re-run
could repeat a model call that was already paid for. The user submits the article again.

Adapted from Charcoal's charcoal/jobs.py (same author), simplified.
"""

from datetime import datetime, timedelta, timezone

from typedb.driver import TypeDBDriverException

from newslens import store
from newslens.db import read, string, write

LEASE = timedelta(minutes=20)        # longer than a run's worst case (fetches + 3 model attempts)


def _at(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def claim_next(driver, db, clock=lambda: datetime.now(timezone.utc)):
    """Claim the oldest queued run; returns its run id, or None if there is nothing to do."""
    rows = read(driver, db, 'match $r isa analysis-run, has run-status "queued", has created-at $t; '
                            'sort $t asc; limit 5; fetch { "id": $r.run-id };')
    for row in rows:
        try:
            [count] = write(driver, db, f'match $r isa analysis-run, has run-id {string(row["id"])}, '
                                        f'has run-status "queued"; update $r has run-status "running"; '
                                        f'$r has lease-until {_at(clock() + LEASE)};')
        except TypeDBDriverException as error:
            if "isolation conflict" in str(error):
                continue                # another worker claimed it first
            raise
        if count == 1:
            return row["id"]
    return None


def renew(driver, db, run_id, clock=lambda: datetime.now(timezone.utc)):
    write(driver, db, f'match $r isa analysis-run, has run-id {string(run_id)}, has run-status "running"; '
                      f'update $r has lease-until {_at(clock() + LEASE)};')


def recover_abandoned(driver, db, clock=lambda: datetime.now(timezone.utc)):
    """Mark runs whose lease has expired as failed; returns their ids."""
    rows = read(driver, db, f'match $r isa analysis-run, has run-status "running", has lease-until $l; '
                            f'$l < {_at(clock())}; fetch {{ "id": $r.run-id }};')
    for row in rows:
        store.fail_running_stages(driver, db, row["id"], "The worker stopped before this stage finished.")
        store.finish_run(driver, db, row["id"], "failed",
                         "Interrupted: the worker stopped before the run finished. It was not "
                         "restarted automatically, so no model call is repeated; submit the article again.")
    return [row["id"] for row in rows]

"""Creating the database and applying schema changes in order, once each.

A new database gets schema/schema.tql (recorded as migration "000-base") followed by every
file in schema/migrations/. An existing database gets only the migrations it hasn't had.
The database records each one as a schema-migration entity, so it always knows where it is.

Adapted from Charcoal's charcoal/migrations.py (same author).
"""

from pathlib import Path

from typedb.driver import TransactionType

from newslens.db import now, read, run_file, string, write

ROOT = Path(__file__).parent.parent
BASE_SCHEMA = ROOT / "schema" / "schema.tql"
MIGRATIONS = ROOT / "schema" / "migrations"
BASE_ID = "000-base"


def migration_files():
    return sorted(MIGRATIONS.glob("[0-9][0-9][0-9]-*.tql"))


def applied(driver, db):
    """IDs of migrations already applied to this database."""
    rows = read(driver, db, 'match $m isa schema-migration; fetch { "id": $m.migration-id };')
    return {row["id"] for row in rows}


def _record(driver, db, migration_id):
    write(driver, db, f"insert $m isa schema-migration, has migration-id {string(migration_id)}, "
                      f"has applied-at {now()};")


def apply(driver, db):
    """Apply every pending migration in order; returns the IDs applied."""
    done, newly_applied = applied(driver, db), []
    for path in migration_files():
        if path.stem in done:
            continue
        run_file(driver, db, path, TransactionType.SCHEMA)
        _record(driver, db, path.stem)
        newly_applied.append(path.stem)
    return newly_applied


def create_schema(driver, db):
    """Give a new, empty database the complete current schema."""
    run_file(driver, db, BASE_SCHEMA, TransactionType.SCHEMA)
    _record(driver, db, BASE_ID)
    return [BASE_ID, *apply(driver, db)]


def ensure_database(driver, db):
    """Make sure the database exists and is up to date; returns the migration IDs applied now."""
    if not driver.databases.contains(db):
        driver.databases.create(db)
        return create_schema(driver, db)
    return apply(driver, db)


def schema_version(driver, db):
    """The latest migration applied to this database, e.g. "000-base"."""
    done = applied(driver, db)
    return max(done) if done else None

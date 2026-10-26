"""Connecting to TypeDB and running queries. Everything else in NewsLens uses this.

Adapted from Charcoal's charcoal/db.py (same author).
"""

from datetime import datetime, timezone
from pathlib import Path

from typedb.driver import Credentials, DriverOptions, DriverTlsConfig, TransactionType, TypeDB


def connect(settings):
    """Open a connection ("driver") to the TypeDB server described in the settings."""
    return TypeDB.driver(
        settings.typedb_address,
        Credentials(settings.typedb_username, settings.typedb_password.get_secret_value()),
        # The local server has TLS (encryption) switched off; see compose.yaml.
        DriverOptions(DriverTlsConfig.disabled()),
    )


def string(value):
    """Write a Python string as a TypeQL string, escaping characters that would break it.

    Always use this when putting text into a query, never plain quotes.
    """
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"')
        .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    )
    return f'"{escaped}"'


def now():
    """The current time as a TypeQL datetime-tz literal (UTC, to the millisecond)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read(driver, db, query):
    """Run a fetch query in a READ transaction and return the results as a list.

    A READ transaction can only look at data, never change it.
    """
    with driver.transaction(db, TransactionType.READ) as tx:
        return list(tx.query(query).resolve().as_concept_documents())


def write(driver, db, *queries):
    """Run one or more queries in ONE write transaction and commit: all of them or none.

    Returns how many rows each query matched. A `match ... insert` whose match finds nothing
    inserts nothing, silently, so callers check the counts.
    """
    with driver.transaction(db, TransactionType.WRITE) as tx:
        counts = [len(list(tx.query(query).resolve().as_concept_rows())) for query in queries]
        tx.commit()
        return counts


def run_file(driver, db, path, kind=TransactionType.SCHEMA):
    """Run a whole .tql file as one query (used for the schema)."""
    with driver.transaction(db, kind) as tx:
        tx.query(Path(path).read_text()).resolve()
        tx.commit()

"""Saving and reading articles and analysis runs in TypeDB.

Milestone 1 records a submitted URL as an article with retrieval status "queued", plus a
queued analysis run under the current methodology. Nothing is fetched or analysed yet.
Reads use READ transactions only.
"""

import uuid

from newslens.db import now, read, string, write

METHODOLOGY_VERSION = "0.0-foundation"
METHODOLOGY_DESCRIPTION = ("Milestone 1 foundation: submitted articles and analysis runs are "
                           "recorded. No retrieval or analysis is performed.")


class NotSaved(Exception):
    """A write matched nothing, so nothing was saved (see db.write)."""


def ensure_methodology(driver, db):
    """Record the current methodology version, once."""
    rows = read(driver, db, f'match $m isa methodology, has methodology-version '
                            f'{string(METHODOLOGY_VERSION)}; fetch {{ "v": $m.methodology-version }};')
    if not rows:
        write(driver, db, f'insert $m isa methodology, has methodology-version '
                          f'{string(METHODOLOGY_VERSION)}, has description '
                          f'{string(METHODOLOGY_DESCRIPTION)};')


def submit_url(driver, db, url):
    """Save a submitted URL as a queued article with a queued run; returns the article id."""
    article_id, run_id, created = uuid.uuid4().hex, uuid.uuid4().hex, now()
    [count] = write(driver, db, f"""
        match $m isa methodology, has methodology-version {string(METHODOLOGY_VERSION)};
        insert
          $a isa article, has doc-id {string(article_id)}, has url {string(url)},
            has retrieval-status "queued", has input-method "url", has created-at {created};
          $r isa analysis-run, has run-id {string(run_id)}, has run-status "queued",
            has created-at {created};
          run-target (run: $r, article: $a, methodology: $m);
    """)
    if count != 1:
        raise NotSaved(f"expected to save 1 article, saved {count}")
    return article_id


_ARTICLE_FIELDS = """
    "id": $a.doc-id, "url": $a.url, "title": $a.title,
    "retrieval_status": $a.retrieval-status, "input_method": $a.input-method,
    "created_at": $a.created-at,
    "runs": [
      match run-target (run: $r, article: $a, methodology: $m);
      fetch { "id": $r.run-id, "status": $r.run-status, "created_at": $r.created-at,
              "methodology_version": $m.methodology-version };
    ]
"""


def _clean(row):
    row["created_at"] = str(row["created_at"])
    row["runs"] = sorted(({**run, "created_at": str(run["created_at"])} for run in row["runs"]),
                         key=lambda run: run["created_at"])
    return row


def get_article(driver, db, article_id):
    """One article with its runs, or None if there is no such article."""
    rows = read(driver, db, f"match $a isa article, has doc-id {string(article_id)}; "
                            f"fetch {{ {_ARTICLE_FIELDS} }};")
    return _clean(rows[0]) if rows else None


def list_articles(driver, db, limit=50):
    """The most recently submitted articles, newest first."""
    rows = read(driver, db, f"match $a isa article, has created-at $t; sort $t desc; "
                            f"limit {int(limit)}; fetch {{ {_ARTICLE_FIELDS} }};")
    return [_clean(row) for row in rows]


def count_queued_runs(driver, db):
    rows = read(driver, db, 'match $r isa analysis-run, has run-status "queued"; '
                            'fetch { "id": $r.run-id };')
    return len(rows)

"""The schema loads, refuses malformed records itself, and keeps provenance traceable."""

import pytest
from typedb.driver import TypeDBDriverException

from newslens import migrations
from newslens.db import now, read, write
from newslens.migrations import BASE_ID, applied, ensure_database, schema_version

T = now()
ARTICLE = 'has input-method "url", has created-at ' + T


LATEST = migrations.migration_files()[-1].stem


def test_new_database_gets_base_schema_and_every_migration(db, driver):
    assert applied(driver, db) == {BASE_ID, *(p.stem for p in migrations.migration_files())}
    assert schema_version(driver, db) == LATEST


def test_ensure_database_is_idempotent(db, driver):
    before = applied(driver, db)
    assert ensure_database(driver, db) == []
    assert applied(driver, db) == before


def test_pending_migration_applied_once(db, driver, tmp_path, monkeypatch):
    (tmp_path / "999-test-note.tql").write_text(
        "define attribute test-note, value string; entity article, owns test-note @card(0..1);")
    monkeypatch.setattr(migrations, "MIGRATIONS", tmp_path)
    assert ensure_database(driver, db) == ["999-test-note"]
    assert ensure_database(driver, db) == []
    assert schema_version(driver, db) == "999-test-note"


@pytest.mark.parametrize("label, query, code", [
    ("missing retrieval-status", f'insert $a isa article, has doc-id "a2", {ARTICLE};', "CNT5"),
    ("unknown status value",
     f'insert $a isa article, has doc-id "a3", has retrieval-status "maybe", {ARTICLE};', "CNT8"),
    ("malformed content hash",
     f'insert $a isa article, has doc-id "a4", has retrieval-status "queued", '
     f'has content-hash "abc", {ARTICLE};', "CNT6"),
    ("two headlines",
     f'insert $a isa article, has doc-id "a5", has retrieval-status "queued", '
     f'has title "x", has title "y", {ARTICLE};', "CNT5"),
    ("claim without a kind",
     'insert $c isa claim, has claim-id "c9", has claim-text "x", has basis "stated";', "CNT5"),
    ("claim with unknown basis",
     'insert $c isa claim, has claim-id "c9", has claim-text "x", has claim-kind "factual", '
     'has basis "vibes";', "CNT8"),
])
def test_schema_refuses_malformed_records(db, driver, label, query, code):
    with pytest.raises(TypeDBDriverException, match=code):
        write(driver, db, query)


def test_duplicate_ids_refused(db, driver):
    write(driver, db, f'insert $a isa article, has doc-id "a1", has retrieval-status "queued", {ARTICLE};')
    with pytest.raises(TypeDBDriverException, match="CNT9"):
        write(driver, db, f'insert $a isa article, has doc-id "a1", has retrieval-status "queued", {ARTICLE};')


def test_claim_traces_to_quote_run_and_methodology(db, driver):
    text = "The mayor said the bridge will close."
    write(driver, db, f"""insert
      $m isa methodology, has methodology-version "test", has description "test";
      $a isa article, has doc-id "a1", has title "Synthetic", has body-text "{text}",
        has retrieval-status "manual", has input-method "manual-text", has created-at {T};
      $s isa text-span, has span-id "s1", has start-offset 0, has end-offset {len(text)},
        has exact-text "{text}";
      span-location (container: $a, span: $s);
      $r isa analysis-run, has run-id "r1", has run-status "completed", has created-at {T};
      run-target (run: $r, article: $a, methodology: $m);
      $c isa claim, has claim-id "c1", has claim-text "The bridge will close.",
        has claim-kind "predictive", has basis "stated";
      claim-anchor (claim: $c, anchor: $s);
      produced-by (output: $c, run: $r);""")
    [row] = read(driver, db, """match
      $c isa claim, has claim-id "c1"; claim-anchor (claim: $c, anchor: $s);
      span-location (container: $a, span: $s); produced-by (output: $c, run: $r);
      run-target (run: $r, article: $a, methodology: $m);
      fetch { "quote": $s.exact-text, "start": $s.start-offset, "end": $s.end-offset,
              "headline": $a.title, "run": $r.run-id, "method": $m.methodology-version };""")
    assert row == {"quote": text, "start": 0, "end": len(text), "headline": "Synthetic",
                   "run": "r1", "method": "test"}

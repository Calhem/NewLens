"""Saving and reading articles, analysis runs, stages and their results in TypeDB.

All TypeQL for the application lives here (and in llm.py for the budget). Reads use READ
transactions only. Each write that saves a stage's results is ONE transaction, so a failure
part-way through stores nothing from that stage.
"""

import hashlib
import uuid
from urllib.parse import urlsplit

from newslens.db import atomically, now, read, string, tx_fetch, write

METHODOLOGY_VERSION = "0.1-ingestion"
METHODOLOGY_DESCRIPTION = (
    "Milestone 2: safe retrieval or manual entry; metadata only from explicit page markup; "
    "quotations found by quotation marks; claims extracted by a model and kept only when their "
    "quote appears verbatim in the article. Claims are not yet assessed.")


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


def _one(tx, query):
    """Run a match-insert/update that must affect exactly one row, inside a transaction."""
    count = len(list(tx.query(query).resolve().as_concept_rows()))
    if count != 1:
        raise NotSaved(f"expected 1 row, got {count}: {query.split(';')[0][:80]}")


def _content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


# --- submitting ---------------------------------------------------------------------------

def _submit(driver, db, article_attributes):
    article_id, run_id, created = uuid.uuid4().hex, uuid.uuid4().hex, now()
    [count] = write(driver, db, f"""
        match $m isa methodology, has methodology-version {string(METHODOLOGY_VERSION)};
        insert
          $a isa article, has doc-id {string(article_id)}, {article_attributes},
            has created-at {created};
          $r isa analysis-run, has run-id {string(run_id)}, has run-status "queued",
            has created-at {created};
          run-target (run: $r, article: $a, methodology: $m);
    """)
    if count != 1:
        raise NotSaved(f"expected to save 1 article, saved {count}")
    return article_id


def submit_url(driver, db, url):
    """Save a submitted URL as a queued article with a queued run; returns the article id."""
    return _submit(driver, db, f'has url {string(url)}, has retrieval-status "queued", '
                               f'has input-method "url"')


def submit_text(driver, db, title, text, url=None):
    """Save manually entered article text with a queued run; returns the article id.

    The text is stored exactly as given: it is what every offset and quote refers to."""
    extra = f", has url {string(url)}" if url else ""
    return _submit(driver, db, f'has title {string(title)}, has body-text {string(text)}, '
                               f'has content-hash "{_content_hash(text)}", '
                               f'has retrieval-status "manual", has input-method "manual-text"{extra}')


# --- runs and stages ----------------------------------------------------------------------

def run_target(driver, db, run_id):
    """What a run needs to start: the article's id, URL, input method and (manual) text."""
    rows = read(driver, db, f"""match $r isa analysis-run, has run-id {string(run_id)};
        run-target (run: $r, article: $a); $a isa article;
        fetch {{ "article_id": $a.doc-id, "url": $a.url, "input_method": $a.input-method,
                 "title": $a.title, "text": $a.body-text }};""")
    return rows[0] if rows else None


def start_stage(driver, db, run_id, stage):
    def work(tx):
        _one(tx, f'match $r isa analysis-run, has run-id {string(run_id)}; '
                 f'update $r has stage {string(stage)};')
        _one(tx, f'match $r isa analysis-run, has run-id {string(run_id)}; '
                 f'insert $s isa analysis-stage, has stage-name {string(stage)}, '
                 f'has stage-status "running", has started-at {now()}; run-stage (run: $r, stage: $s);')
    atomically(driver, db, work)


def finish_stage(driver, db, run_id, stage, status, details=()):
    def work(tx):
        match = (f'match $r isa analysis-run, has run-id {string(run_id)}; run-stage (run: $r, stage: $s); '
                 f'$s isa analysis-stage, has stage-name {string(stage)};')
        _one(tx, f'{match} update $s has stage-status {string(status)}; $s has finished-at {now()};')
        for detail in details:
            _one(tx, f'{match} insert $s has stage-detail {string(detail[:1000])};')
    atomically(driver, db, work)


def fail_running_stages(driver, db, run_id, detail):
    """Mark any stage still "running" as failed (after a crash or an unexpected error)."""
    rows = read(driver, db, f'match $r isa analysis-run, has run-id {string(run_id)}; '
                            f'run-stage (run: $r, stage: $s); $s has stage-status "running"; '
                            f'fetch {{ "name": $s.stage-name }};')
    for row in rows:
        finish_stage(driver, db, run_id, row["name"], "failed", [detail])


def finish_run(driver, db, run_id, status, reason=None):
    def work(tx):
        match = f'match $r isa analysis-run, has run-id {string(run_id)};'
        _one(tx, f'{match} update $r has run-status {string(status)}; $r has finished-at {now()};')
        if reason:
            _one(tx, f'{match} update $r has failure-reason {string(reason[:1000])};')
    atomically(driver, db, work)


# --- stage results ------------------------------------------------------------------------

def save_retrieval(driver, db, article_id, status, notes, response=None):
    """What retrieval found: status, notes, and (if anything came back) HTTP details."""
    def work(tx):
        match = f'match $a isa article, has doc-id {string(article_id)};'
        _one(tx, f'{match} update $a has retrieval-status {string(status)};')
        for note in notes:
            _one(tx, f'{match} insert $a has retrieval-note {string(note[:1000])};')
        if response is not None:
            if response.status is not None:
                _one(tx, f'{match} update $a has http-status {int(response.status)};')
            if response.final_url:
                _one(tx, f'{match} update $a has final-url {string(response.final_url)};')
            _one(tx, f'{match} update $a has retrieved-at {now()};')
    atomically(driver, db, work)


def _publisher_id(host):
    host = (host or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def save_extraction(driver, db, article_id, run_id, extracted, source_url=None, manual=False):
    """Everything extraction found, in one transaction: text, metadata (with sources),
    publisher, quotations with offsets, and links."""
    def work(tx):
        match = f'match $a isa article, has doc-id {string(article_id)};'
        sets = []
        if not manual:
            text = extracted.text
            sets += [f"$a has body-text {string(text)};", f'$a has content-hash "{_content_hash(text)}";']
            if extracted.headline:
                sets.append(f"$a has title {string(extracted.headline[:500])};")
        for field, attr in (("subheading", "subheading"), ("canonical_url", "canonical-url"),
                            ("language", "language")):
            value = getattr(extracted, field)
            if value:
                sets.append(f"$a has {attr} {string(value[:2000])};")
        for field, attr in (("published_at", "published-at"), ("modified_at", "modified-at")):
            value = getattr(extracted, field)
            if value:
                sets.append(f"$a has {attr} {value};")
        if sets:
            _one(tx, f"{match} update {' '.join(sets)}")
        for value, attr in ([(s, "metadata-source") for s in extracted.sources]
                            + [(n[:300], "byline-name") for n in extracted.authors]):
            _one(tx, f"{match} insert $a has {attr} {string(value)};")

        host = urlsplit(source_url).hostname if source_url else None
        if host:
            publisher_id = _publisher_id(host)
            if not tx_fetch(tx, f'match $p isa publisher, has publisher-id {string(publisher_id)}; '
                                f'fetch {{ "id": $p.publisher-id }};'):
                tx.query(f'insert $p isa publisher, has publisher-id {string(publisher_id)}, '
                         f'has name {string((extracted.publisher_name or publisher_id)[:300])}, '
                         f'has domain {string(publisher_id)};').resolve()
            _one(tx, f'{match} $p isa publisher, has publisher-id {string(publisher_id)}; '
                     f'insert publication (publisher: $p, published: $a);')

        for i, quote in enumerate(extracted.quotes):
            _one(tx, f'{match} $r isa analysis-run, has run-id {string(run_id)}; '
                     f'insert $q isa quotation, has span-id "{article_id}-q{i}", '
                     f'has start-offset {quote.start}, has end-offset {quote.end}, '
                     f'has exact-text {string(quote.text)}; span-location (container: $a, span: $q); '
                     f'produced-by (output: $q, run: $r);')
        for link in extracted.links:
            anchor = f", has anchor-text {string(link.anchor_text[:500])}" if link.anchor_text else ""
            _one(tx, f'{match} insert $l isa hyperlink, has url {string(link.url)}{anchor}; '
                     f'link-location (container: $a, link: $l);')
    atomically(driver, db, work)


def save_claims(driver, db, article_id, run_id, extraction):
    """Validated claims (each with its anchor span) and speaker attributions, in one
    transaction, each linked to the run that produced it."""
    def work(tx):
        article = f'$a isa article, has doc-id {string(article_id)};'
        run = f'$r isa analysis-run, has run-id {string(run_id)};'
        for i, claim in enumerate(extraction.claims):
            claim_id, span_id = f"{run_id}-c{i}", f"{run_id}-c{i}-anchor"
            missing = "".join(f", has missing-information {string(m)}" for m in claim.missing_information)
            _one(tx, f'match {article} {run} insert '
                     f'$s isa text-span, has span-id {string(span_id)}, has start-offset {claim.start}, '
                     f'has end-offset {claim.end}, has exact-text {string(claim.quote)}; '
                     f'span-location (container: $a, span: $s); '
                     f'$c isa claim, has claim-id {string(claim_id)}, has claim-text {string(claim.text)}, '
                     f'has claim-kind {string(claim.kind)}, has basis {string(claim.basis)}{missing}; '
                     f'$ca isa claim-anchor (claim: $c, anchor: $s); '
                     f'produced-by (output: $c, run: $r); produced-by (output: $s, run: $r); '
                     f'produced-by (output: $ca, run: $r);')
        for speaker in extraction.speakers:
            actor_id = f"{article_id}:{speaker.kind}:{speaker.name.lower()}"
            if not tx_fetch(tx, f'match $p isa actor, has actor-id {string(actor_id)}; '
                                f'fetch {{ "id": $p.actor-id }};'):
                tx.query(f'insert $p isa {"person" if speaker.kind == "person" else "organisation"}, '
                         f'has actor-id {string(actor_id)}, has name {string(speaker.name)};').resolve()
            _one(tx, f'match {run} $q isa quotation, has span-id "{article_id}-q{speaker.quotation}"; '
                     f'$p isa actor, has actor-id {string(actor_id)}; '
                     f'insert $sa isa speaker-attribution (quotation: $q, speaker: $p), '
                     f'has confidence {string(speaker.confidence)}; produced-by (output: $sa, run: $r);')
    atomically(driver, db, work)


# --- reading ------------------------------------------------------------------------------

_SUMMARY_FIELDS = """
    "id": $a.doc-id, "url": $a.url, "title": $a.title,
    "retrieval_status": $a.retrieval-status, "input_method": $a.input-method,
    "created_at": $a.created-at,
    "runs": [
      match run-target (run: $r, article: $a, methodology: $m);
      fetch { "id": $r.run-id, "status": $r.run-status, "stage": $r.stage,
              "created_at": $r.created-at, "finished_at": $r.finished-at,
              "failure_reason": $r.failure-reason,
              "methodology_version": $m.methodology-version,
              "stages": [
                match run-stage (run: $r, stage: $s);
                fetch { "name": $s.stage-name, "status": $s.stage-status,
                        "started_at": $s.started-at, "finished_at": $s.finished-at,
                        "details": [$s.stage-detail] };
              ],
              "model_calls": [
                match run-call (run: $r, call: $c); $c isa model-call;
                fetch { "model": $c.model-id, "prompt_version": $c.prompt-version,
                        "status": $c.call-status, "input_tokens": $c.input-tokens,
                        "output_tokens": $c.output-tokens };
              ] };
    ]
"""

_DETAIL_FIELDS = """
    "subheading": $a.subheading, "canonical_url": $a.canonical-url, "final_url": $a.final-url,
    "http_status": $a.http-status, "published_at": $a.published-at, "modified_at": $a.modified-at,
    "retrieved_at": $a.retrieved-at, "language": $a.language, "text": $a.body-text,
    "content_hash": $a.content-hash,
    "bylines": [$a.byline-name], "metadata_sources": [$a.metadata-source],
    "retrieval_notes": [$a.retrieval-note],
    "publishers": [
      match publication (publisher: $p, published: $a);
      fetch { "name": $p.name, "domain": $p.publisher-id };
    ],
    "quotations": [
      match span-location (container: $a, span: $q); $q isa quotation;
      fetch { "id": $q.span-id, "start": $q.start-offset, "end": $q.end-offset,
              "text": $q.exact-text,
              "speakers": [
                match $sa isa speaker-attribution (quotation: $q, speaker: $p);
                fetch { "name": $p.name, "confidence": $sa.confidence };
              ] };
    ],
    "links": [
      match link-location (container: $a, link: $l);
      fetch { "url": $l.url, "anchor_text": $l.anchor-text };
    ],
    "claims": [
      match span-location (container: $a, span: $s); claim-anchor (claim: $c, anchor: $s);
        produced-by (output: $c, run: $r);
      fetch { "id": $c.claim-id, "text": $c.claim-text, "kind": $c.claim-kind,
              "basis": $c.basis, "missing_information": [$c.missing-information],
              "quote": $s.exact-text, "start": $s.start-offset, "end": $s.end-offset,
              "run_id": $r.run-id };
    ]
"""

_TIMES = ("created_at", "finished_at", "started_at", "published_at", "modified_at", "retrieved_at")


def _clean(value):
    """Datetimes to strings, recursively; runs and stages in time order."""
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        out = {k: (str(v) if k in _TIMES and v is not None else _clean(v)) for k, v in value.items()}
        for key, order in (("runs", "created_at"), ("stages", "started_at")):
            if key in out:
                out[key] = sorted(out[key], key=lambda item: item[order] or "")
        for key in ("quotations", "claims"):
            if key in out:
                out[key] = sorted(out[key], key=lambda item: (item["start"], item["end"]))
        return out
    return value


def get_article(driver, db, article_id, detail=False):
    """One article with its runs (and, with detail, its text and findings), or None."""
    fields = _SUMMARY_FIELDS + ("," + _DETAIL_FIELDS if detail else "")
    rows = read(driver, db, f"match $a isa article, has doc-id {string(article_id)}; "
                            f"fetch {{ {fields} }};")
    return _clean(rows[0]) if rows else None


def list_articles(driver, db, limit=50):
    """The most recently submitted articles, newest first."""
    rows = read(driver, db, f"match $a isa article, has created-at $t; sort $t desc; "
                            f"limit {int(limit)}; fetch {{ {_SUMMARY_FIELDS} }};")
    return [_clean(row) for row in rows]


def count_queued_runs(driver, db):
    rows = read(driver, db, 'match $r isa analysis-run, has run-status "queued"; '
                            'fetch { "id": $r.run-id };')
    return len(rows)

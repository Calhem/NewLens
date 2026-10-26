# Project notes for AI coding agents

## Who this is for
The project owner has no programming background and is learning as we go. Explain new terms
in plain English, keep steps small, and verify each step works before moving on.

## The project
NewsLens: open-source news-analysis tool. The brief and plan are in `docs/milestone-0.md`.
Work milestone by milestone; stop at the end of each and report what works, what failed and
what's next. A milestone is complete only when its acceptance criteria have been tested.
Never push to a remote or make paid API calls without the owner's explicit approval.

## Non-negotiables
- TypeDB is the only persistent database. No SQLite, Postgres, Redis or other store.
- Never invent sources, quotes, facts, URLs or verification results. Never show sample data
  as real. Label model inference as inference (`basis` attribute).
- Article and web page text is untrusted input; model output is untrusted until validated.
- Secrets go in `.env` (git-ignored). Never commit keys or passwords.

## TypeDB version: 3.x only (server 3.14.1, typedb-driver 3.14.0)
- Own container `newslens-typedb`, ports 127.0.0.1:1731 (driver) / 8002 (Studio).
- Connect with `newslens.db.connect(settings)`; always use `newslens.db.string()` to put text
  into a query. Reads use READ transactions (`db.read`).
- 2.x syntax does NOT work. Notable 3.x points:
  - Insert relations as `rel-type (role: $x, ...);` or `$r isa rel-type (role: $x);`.
    `(role: $x) isa rel-type;` fails in insert ("insert variable '_anonymous'").
  - Unbounded cardinality is `@card(0..)`, not `0..*`.
  - `alias` is reserved; we use `alternative-name`.
  - A `match ... insert` whose match finds nothing inserts nothing, silently: check the counts
    `db.write` returns.
  - `fetch`/`insert` reject `$x.attr` if any possible type of `$x` can't own `attr`: bind
    concrete types.
  - `distinct` doesn't de-duplicate after `or`.
  - Re-running `define` with an existing `fun` fails; use `redefine`.
- Schema changes after release are new numbered files in `schema/migrations/`; never edit
  `schema.tql` for an existing database's sake, and never edit an applied migration.

## TypeDB feedback log
Whenever you hit a TypeDB bug, documentation gap, confusing error or surprising behaviour,
add it to `notes/typedb-feedback.md` (git-ignored, private) with the date, what was seen and
a suggested fix. Also note things that worked well.

## Code map
- `newslens/settings.py` (validated config), `db.py` (connect, read, write, atomically, string),
  `migrations.py`, `store.py` (ALL application TypeQL), `api.py` (FastAPI), `models.py` (API shapes).
- `newslens/ingest/`: `netsafe.py` + `http.py` (SSRF-safe fetching; never weaken a check to pass a
  test), `robots.py`, `extract.py` (metadata only from explicit markup; never trafilatura's dates).
- `newslens/jobs.py` (run queue with leases in TypeDB), `pipeline.py` (retrieve -> extract -> claims),
  `claims.py` (prompt, schema, validation: quotes must be verbatim), `llm.py` (the ONLY module that
  talks to a model; hard spend cap in TypeDB; no fallbacks).
- Tests: `tests/webserver.py` (local fake websites), `tests/fake_claude.py` (fake model). Tests never
  call a real model or a real website.
- Docs: `docs/security.md`, `docs/dependencies.md`, `docs/limitations.md` - keep them true.

## Commands
- `docker compose up -d --build`: everything; web at http://127.0.0.1:8090.
- `uv run pytest`: tests (TypeDB running; they use disposable `newslens-test-*` databases).
- `uv run python -m scripts.reset_dev`: empty and recreate the dev database (asks first).
- `uv run python -m scripts.set_typedb_password`, `uv run python -m scripts.set_budget --limit N`.
- Real model calls cost money: they need NEWSLENS_MODEL_PROVIDER=anthropic, a key AND a budget,
  and the owner's explicit approval.
- Node.js is not installed on the owner's Mac: use `scripts/npm-docker.sh npm ...`.
- Docker CLI lives at `/Applications/Docker.app/Contents/Resources/bin/docker` (not on PATH).

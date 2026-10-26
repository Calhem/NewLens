# NewsLens: Milestone 0 technical plan

Status: **approved 2026-10-26.** Decision A (separate folder and container) and B (MIT) were
approved. For D, Node.js runs from the official Docker image (`scripts/npm-docker.sh`), so
nothing needs installing; installing Node 24 LTS locally remains optional. C (search provider)
is decided at Milestone 3. Milestone 1 is implemented; see the README for its status.

## 1. Where things stand (verified 2026-10-26)

| Check | Result |
|---|---|
| Starting repository | The session opened in `typedb-cyber-intel` (the CAO threat-intelligence app, clean `main`, 11 commits). It is unrelated to NewsLens and is **not touched**. |
| NewsLens location | New folder `~/Desktop/TypeDB/newslens`, its own git repository, its own TypeDB container, following the Charcoal precedent. **(to confirm)** |
| Docker | Docker Desktop 29.9.2 is running. The `docker` command is not on the shell's PATH (it lives at `/Applications/Docker.app/Contents/Resources/bin/docker`); the README will cover this. Existing containers `typedb` (1729/8000) and `charcoal-typedb` (1730/8001) are stopped and stay untouched. |
| TypeDB | CE **3.14.1** is the newest image on Docker Hub. Python driver `typedb-driver` **3.14.0** is the newest on PyPI and is the version proven in both earlier projects. |
| Python | uv 0.13.5, Python 3.13. FastAPI 0.162.0, Pydantic 2.14.1, trafilatura 2.3.1, anthropic 2.3.0 are current. |
| Node.js | **Not installed.** Needed for React/Vite development. See decision D. |
| Frontend packages | React 19.3.1, Vite 8.3.5, Tailwind CSS 4.3.3, shadcn CLI 4.22.1, @xyflow/react 12.12.0, cytoscape 3.34.4. TypeScript's latest is **7.0.2** (the new native compiler); we use whatever version the official Vite React template pins, to avoid tooling mismatches. |
| GitHub CLI | Not installed (not needed until publishing). |

### Skills

- **Frontend Design**: *not installed*. It is available as Anthropic's official `frontend-design`
  plugin (Anthropic Directory). I read its actual instructions from the source repository
  (`anthropics/claude-plugins-official`, `plugins/frontend-design`). It has no dependencies.
  Its method: define the subject, plan a compact token system (4-6 named colours, type roles,
  ASCII wireframes), review the plan against the brief, build, then critique with screenshots.
  It explicitly warns against two layouts that sit close to our brief: "broadsheet hairlines
  with zero radius and dense columns" and template chrome such as all-caps eyebrows and
  monospace data labels. The design directions must earn their editorial/intelligence character
  from the subject, not from those defaults.
- **shadcn/ui** is not a skill or a package you install whole: its CLI copies component source
  into our project (`src/components/ui/`), which we then own and restyle. Official Vite route:
  create a React + TypeScript Vite app, add Tailwind v4 via `@tailwindcss/vite`, set the `@/*`
  path alias, then `npx shadcn@latest init` and `npx shadcn@latest add <component>`. We add
  only components we use, and restyle them to the chosen direction rather than keeping the
  default look.
- Other installed skills (`artifact-design`, `dataviz`, `code-review`, `security-review`) are
  useful later: `dataviz` for any chart, `security-review` before release.

## 2. Existing work worth reusing

Charcoal (`~/Desktop/TypeDB/charcoal`, Apache-2.0, same copyright holder) already solved
several NewsLens problems with tests. Copy and adapt, with attribution in the commit message:

| Charcoal module | NewsLens use |
|---|---|
| `collect/netsafe.py` | SSRF protection: resolves DNS itself, refuses private, loopback, link-local, metadata, CGNAT and NAT64-embedded addresses, connects to the checked address (no DNS rebinding). |
| `collect/fetch.py` | Bounded GET: manual redirects (each hop re-checked), byte cap, per-step and total timeouts, per-host rate limit. |
| `collect/robots.py` | robots.txt, plus a separate "may this text go to an AI provider" check. |
| `collect/extract.py` | trafilatura main-text extraction; dates only from machine-readable metadata. |
| `llm.py` | The single place that calls Claude; hard spend cap reserved in TypeDB before each call. |
| `jobs.py` | Background jobs stored in TypeDB with leases and crash recovery: no Redis, no second database. |
| `db.py`, `migrations.py` | Driver connection, safe string escaping, numbered schema migrations. |

From the CTI project: the evidence-route discipline (every answer carries the claim IDs behind
it) and citation checking of model output. The TypeDB 3.x pitfalls in that project's
`CLAUDE.md` carry over to NewsLens's `CLAUDE.md`.

## 3. Recommended architecture

```
browser ──► web (React/Vite build, served by nginx in Docker; Vite dev server locally)
              │  JSON over HTTP, /api/*
              ▼
            api (FastAPI + Pydantic) ── submit, read results, health; READ transactions for reads
              │
              ├──► TypeDB 3.14.1 (only persistent store: content, findings, runs, jobs, budget)
              ▲
            worker (same Python package) ── claims queued analysis runs from TypeDB, runs the pipeline
              │
              ├──► FetchProvider  (our safe fetcher; the model never fetches URLs)
              ├──► SearchProvider (interface; first implementation: see decision C)
              └──► ModelProvider  (interface; first implementation: Claude)
```

**Pipeline stages** (each a function with typed Pydantic input/output, each result stored before
the next starts, so a crash resumes and every stage can be inspected):

1. `retrieve`: safe fetch or manual text; record exactly what was and wasn't retrieved.
2. `extract`: metadata, body, quotations with speakers, links. Character offsets into the stored text.
3. `claims`: atomic claims, each anchored to an exact quote that is checked against the stored
   text (a quote that isn't found verbatim is rejected, not stored).
4. `research` (M3): search queries per claim; candidate sources fetched by our fetcher.
5. `assess` (M3): stance of each evidence excerpt; per-claim assessment.
6. `framing` / `arguments` / `inferences` (M4).
7. `coverage` / `compare` (M5).

**Trust boundaries.** Article and page text is untrusted: it goes to the model only inside
clearly delimited data blocks, with the instruction that it is material to analyse, never
instructions. The model gets narrow tools with validated arguments (for example "search for
this query", capped per run), never "fetch any URL" or code execution. All model output is
parsed into strict Pydantic models; anything that fails validation is recorded as a failed
stage, never partly written. React renders text only (no `dangerouslySetInnerHTML`); stored
HTML is never served back.

**Why these choices.** The brief fixes React/Vite/Tailwind/shadcn, FastAPI/Pydantic and
TypeDB. Within that: a TypeDB-backed job queue keeps "TypeDB is the only persistent database"
literally true (Celery/RQ would need Redis); one Python package for api and worker means one
set of models and tests; nginx serving the static build keeps the production container free of
Node.

## 4. Proposed initial TypeDB schema (first release: M1-M3)

Design rules: every model-generated record links to the `analysis-run` that produced it (model
ID, prompt version, methodology version, time). Every finding says what it rests on:
`basis` = `stated` (the article says it), `implied` (follows from the article's text) or
`model-inferred` (our interpretation). Text anchors are `text-span`s with offsets into a
stored, hashed document text, so a quote can always be re-checked.

**Entities**

| Type | Key attributes (cardinality) |
|---|---|
| `document` (abstract) | `doc-id @key`, `url`, `canonical-url 0..1`, `title 0..1`, `body-text 0..1`, `content-hash 0..1`, `published-at 0..1`, `modified-at 0..1`, `retrieved-at 0..1`, `retrieval-status` |
| `article` sub document | `subheading 0..1`, `input-method` (url / manual) |
| `source-document` sub document | `source-kind` (primary / secondary / wire / press-release / unknown) |
| `publisher` | `publisher-id @key`, `name`, `domain 0..*` |
| `actor` (abstract) → `person`, `organisation` | `actor-id @key`, `name`, `alternative-name 0..*` |
| `event` | `event-id @key`, `name`, `description 0..1`, `occurred-at 0..1` |
| `text-span` | `span-id @key`, `start-offset`, `end-offset`, `exact-text` |
| `quotation` sub text-span | (speaker via relation) |
| `claim` | `claim-id @key`, `claim-text`, `claim-kind` (factual / causal / predictive / interpretive / normative / opinion), `basis`, `missing-information 0..*` |
| `assessment` | `assessment-id @key`, `verdict` (supported / contradicted / partially-supported / disputed / unverifiable / not-assessed), `confidence` (high / medium / low), `explanation`, `created-at` |
| `analysis-run` | `run-id @key`, `run-status`, `stage 0..1`, `created-at`, `finished-at 0..1`, `lease-until 0..1`, `failure-reason 0..1` |
| `methodology` | `methodology-version @key`, `description` |
| `model-call` | `call-id @key`, `model-id`, `prompt-version`, `input-tokens`, `output-tokens`, `cost-estimate` |
| `search-query` (M3) | `query-text`, `provider`, `issued-at`, `result-count` |
| Later (M4/M5): `framing-finding`, `explicit-argument`, `implicit-inference`, `alternative-interpretation`, `narrative`, `coverage-comparison`, `user-challenge` | sketched now so relations fit; defined in their milestone's migration |

**Relations**

| Relation | Roles | Notes |
|---|---|---|
| `publication` | `publisher`, `published` (document) | `0..1` publisher per document |
| `authorship` | `author` (person), `work` (document) | |
| `span-location` | `container` (document), `span` | every span belongs to exactly one document |
| `speaker-attribution` | `quotation`, `speaker` (actor) | owns `attribution-confidence` |
| `claim-anchor` | `claim`, `anchor` (text-span) | `1..*` anchors per claim: no claim without text |
| `claim-subject` | `claim`, `subject` (actor / event) | entities, dates, quantities in the claim |
| `coverage` | `report` (article), `event` | owns `relevance` (same-event / related-topic) |
| `evidence` | `claim`, `excerpt` (text-span in a source-document) | owns `stance` (supports / contradicts / qualifies / context), `explanation` |
| `assessment-of` | `assessment`, `claim`, `cited` (evidence) | an assessment cites the evidence relations it used; `not-assessed` cites none |
| `source-dependency` | `dependent` (document), `origin` (document) | owns `dependency-kind` (same wire copy / same press release / quotes same statement); stops three copies counting as three confirmations |
| `produced-by` | `output` (claim / assessment / span / ...), `run` | provenance for everything model-made |
| `run-target` | `run`, `article`, `methodology` | which article, under which rules |
| `run-call` | `run`, `call` (model-call / search-query) | cost and reproducibility |

Schema changes after the first real database are numbered files in `schema/migrations/`, as in
the other projects. The schema will be loaded and probed on the real server at the start of M1
(a throwaway database), before any application code depends on it.

## 5. Deployment shape

`compose.yaml` with services `typedb` (3.14.1, own volume `newslens-typedb-data`, ports
**127.0.0.1:1731** driver / **127.0.0.1:8002** Studio, so it can run next to CAO and Charcoal),
`api`, `worker`, `web`. Health checks: TypeDB port check; `api /health` reports TypeDB
reachability and schema version; `web` depends on a healthy `api`. Settings validated at start
with Pydantic Settings: a missing or malformed value stops startup with a plain message naming
the setting. Reset: `scripts.reset_dev` deletes and recreates only the configured dev database
after a typed confirmation.

## 6. Key risks and decisions

**Decisions for the owner**

- **A. Location (to confirm):** separate folder and container as above, rather than inside
  `typedb-cyber-intel`. Recommended: yes.
- **B. Licence:** MIT, per the brief (Charcoal used Apache-2.0; copying our own Charcoal code
  into an MIT project is fine since you hold the copyright).
- **C. Search provider (to confirm, needed at M3, not M1):** recommended first implementation is
  a plain search API called by our code (Brave Search API is the leading candidate; pricing and
  terms to be checked at M3), not a model-driven web tool, so we control rate, cost and which
  pages get fetched. Claude's own server-side web search could be a second provider.
- **D. Node.js (to confirm):** needed on this Mac to build the frontend. Options: install Node 24
  LTS with the official macOS installer (asks for your password; you run it), or run all
  frontend tooling inside a Docker container (nothing installed, slower and harder to debug).
  Recommended: the official installer.
- **E. Model:** Claude (`claude-opus-5-5`) behind the ModelProvider interface, with the Charcoal
  spend cap. Real API calls only with your key and explicit spend approval.

**Risks**

- *Copyright:* storing full article text is needed for traceable quotes but is a retention
  question. Proposed default: keep text for the user's own analyses only, never redistribute it
  in fixtures or exports; document retention; a delete-article command. Test fixtures are
  synthetic.
- *Publisher access:* many news sites block bots or are paywalled. We report "could not
  retrieve" honestly and offer manual text entry; we don't bypass paywalls.
- *Defamation-adjacent output:* findings about named people must be attributed, labelled by
  basis, and never phrased as established fact from model inference alone.
- *Overreach in subtext findings (main product risk):* false positives are the failure mode
  that matters most. M7's benchmark must include articles with **no** narrative injection, and
  "insufficient evidence" must be a first-class result from M4 onward.
- *Model output validity:* quote anchoring by exact match catches invented quotes; schema
  validation catches malformed output; neither proves the analysis is right. That's for M7.
- *Cost:* claim research multiplies calls (claims × searches × pages). Per-run and global budget
  caps from day one.
- *Design tension:* the brief's "editorial + intelligence density" sits near the defaults the
  Frontend Design skill warns about; the three directions must be distinct and grounded.
- *TypeDB 3.x pitfalls* (from earlier projects): match-insert that silently inserts nothing,
  `fetch` rejecting attributes of broad types, no de-duplication after `or`. Loader tests compare
  counts; findings are written per concrete type.

## 7. Milestone 1 plan (runnable foundation)

Small steps, each verified before the next:

1. **Skeleton:** `git init`, MIT `LICENSE`, `.gitignore`, `.env.example`, `README.md` stub,
   `CLAUDE.md` with the TypeDB 3.x rules.
2. **TypeDB container:** `compose.yaml` with `typedb` only; start it; connect from Python.
3. **Schema:** `schema/schema.tql` from section 4 (M1-M3 types); load into a throwaway database;
   probe: insert a sample article, span and claim; confirm a claim can't be stored without an
   anchor relation in our write path; delete the probe database.
4. **Backend:** `newslens/` package: `settings.py` (validated config), `db.py`, `migrations.py`,
   FastAPI app with `GET /api/health` and `POST /api/articles` (stores a submitted URL as an
   `article` with status `queued` and an `analysis-run`; no fetching yet) and
   `GET /api/articles/{id}` (READ transaction).
5. **Tests:** pytest against disposable `newslens-test-*` databases: settings errors, health,
   write-then-read round trip, restart persistence.
6. **Frontend:** (after decision D) Vite React TS app, Tailwind v4, shadcn init, a URL form that
   calls the API and shows the stored record. Plain styling: the visual directions come later,
   at the design step, not in M1.
7. **Compose:** add `api`, `worker` (placeholder loop that claims nothing yet), `web`;
   health checks; README start/stop/reset instructions; `scripts.reset_dev`.
8. **CI:** GitHub Actions workflow file (runs pytest with a TypeDB service container, plus
   frontend typecheck and build). Not pushed anywhere until you approve publishing.
9. **Gate:** start from clean with the README alone, submit a URL in the browser, restart
   everything, confirm the record survives. Report and stop for review.

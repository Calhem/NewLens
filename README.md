# NewsLens

An open-source, self-hostable tool for examining news reporting critically: what an article
states, what it implies, what evidence supports it, and how other publishers cover the same
event. All application data is stored in [TypeDB](https://typedb.com).

## Status: Milestone 2 (article ingestion and claim extraction)

What works now:

- **Submit an article** by address or by pasting its text. A background worker runs the
  analysis in recorded stages: *retrieve* → *extract* → *claims*.
- **Safe retrieval**: public websites only, every redirect checked, size and time limits,
  robots.txt respected, no getting around paywalls or logins. Failures say exactly what
  happened (not permitted, paywalled, failed) and suggest pasting the text. See
  [docs/security.md](docs/security.md).
- **Extraction**: main text, headline, subheading, bylines, publisher, dates, canonical
  address, language, passages in quotation marks (with exact character positions) and links.
  Metadata comes only from the page's own markup, and each value records where it came from;
  nothing is guessed.
- **Claim extraction** (optional, uses a paid AI model): atomic claims with kind and basis, each
  kept only if the passage it quotes appears word for word in the article. Off by default.
- Everything is stored in TypeDB, survives restarts, and is shown in the article view: text
  with marked passages, claims linked to their passages, stages and their outcomes.

What does **not** exist yet: checking claims against evidence (Milestone 3), framing and
implicit-message analysis (4), cross-publisher comparison (5). See
[docs/milestone-0.md](docs/milestone-0.md) for the plan.

## Run it

Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running). The
maintenance scripts below (`uv run python -m scripts...`) also need
[uv](https://docs.astral.sh/uv/), which installs the right Python by itself.

```bash
cp .env.example .env
docker compose up -d --build
```

Then open <http://127.0.0.1:8090>. The first build takes a few minutes.

> On macOS, if your terminal says `docker: command not found`, Docker Desktop's command is
> at `/Applications/Docker.app/Contents/Resources/bin/docker`. Add that folder to your PATH,
> or enable "Install CLI tools" in Docker Desktop's settings.

What starts (`docker compose ps` lists them):

| Service | What it does | Address |
|---|---|---|
| `typedb` | TypeDB 3.14.1, NewsLens's own server and data volume | 127.0.0.1:1731 (driver), 127.0.0.1:8002 (Studio) |
| `api` | FastAPI backend; creates the database and schema on first use | internal only, reached through `web` |
| `worker` | Background worker: retrieves, extracts and (if configured) extracts claims | none |
| `web` | The React interface, served by nginx, which forwards `/api` to `api` | <http://127.0.0.1:8090> |

Every port is bound to 127.0.0.1, so only this computer can connect.

Check health: `curl http://127.0.0.1:8090/api/health`. API documentation is at
<http://127.0.0.1:8090/api/docs>.

Stop: `docker compose down`. Your data stays in the `newslens-typedb-data` volume.

## Configuration

Settings come from `.env` (copy `.env.example`; `.env` is never committed). They are checked at
startup: a missing or malformed value stops the API with a message naming the setting. Run
`docker compose logs api` to see it.

| Setting | Meaning |
|---|---|
| `NEWSLENS_ENVIRONMENT` | `development` (one computer) or `production` (anything shared). `production` refuses insecure defaults such as TypeDB's default password. |
| `TYPEDB_ADDRESS` | `host:port` of TypeDB. `127.0.0.1:1731` for local development; Compose overrides it to `typedb:1729`. |
| `TYPEDB_USERNAME`, `TYPEDB_PASSWORD` | TypeDB login. The defaults are TypeDB CE's built-in `admin` / `password`, accepted only in development. |
| `TYPEDB_DATABASE` | Database name, e.g. `newslens`. |
| `NEWSLENS_MODEL_PROVIDER` | `none` (default: no AI model, claims are skipped) or `anthropic`. |
| `ANTHROPIC_API_KEY` | Needed only with `anthropic`. |

### Changing the TypeDB password

```bash
uv run python -m scripts.set_typedb_password
docker compose up -d --force-recreate api worker
```

It generates a strong random password, sets it on the server and saves it in `.env` without
showing it. After `docker compose down -v` the server is back to its default password, so run
it again.

### Turning on claim extraction (costs money)

Claim extraction uses Claude (`claude-opus-5-5`, $4 per million input tokens and $20 per
million output tokens, checked 2026-10-26; see `config/pricing.toml`). A long article costs at
most about $0.75 to process and usually much less. You need your own Anthropic API key.

1. Save your key with `uv run python -m scripts.set_anthropic_key`. It asks for the key at a
   hidden prompt and writes it to `.env` (readable only by you, never committed); never paste a
   key into chat, source code or a command line. Then set `NEWSLENS_MODEL_PROVIDER=anthropic`
   in `.env`.
2. Set a spending limit (no call is made until you do):
   `uv run python -m scripts.set_budget --limit 5 --warning 4`. Run it without arguments to
   see spending so far.
3. `docker compose up -d --force-recreate worker`.

Each call reserves its maximum possible cost first and is refused if that would pass the
limit. The limit is stored in TypeDB, so restarts can't reset it.

## Resetting development data

- **Empty the database, keep everything else:** with TypeDB running,
  `uv run python -m scripts.reset_dev`. It asks you to type the database name first.
- **Remove everything, including TypeDB's data volume:** `docker compose down -v`. The next
  `docker compose up -d` starts from nothing.

## Development

Backend: Python 3.13 managed by [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d typedb                 # just the database
uv sync
uv run python -m newslens.serve             # API on http://127.0.0.1:8000
uv run python -m newslens.worker            # worker (optional)
uv run pytest                               # tests (TypeDB must be running)
```

Tests create and delete their own `newslens-test-*` databases and never touch `newslens`.

Frontend (`web/`): React, TypeScript, Vite, Tailwind CSS and shadcn/ui. With
[Node.js 24](https://nodejs.org) installed:

```bash
cd web && npm install && npm run dev        # http://127.0.0.1:5173, forwards /api to :8000
```

Without Node.js, `scripts/npm-docker.sh` runs npm inside the official Node Docker image, for
example `scripts/npm-docker.sh npm run build` (it can't run the dev server).

Layout:

```
newslens/        Python package: settings, db, migrations, store, api, serve, worker,
                 jobs (the run queue), pipeline (the stages), claims, llm (model + budget)
newslens/ingest/ safe fetching (http, netsafe), robots.txt rules, extraction
schema/          schema.tql (base schema) and migrations/ (numbered changes, applied once)
config/          pricing.toml (model prices, with the date they were checked)
scripts/         reset_dev, set_typedb_password, set_budget, npm-docker.sh
tests/           pytest suite
web/             React frontend, its Dockerfile and nginx.conf
docs/            plan (milestone-0.md), security.md, dependencies.md, limitations.md
```

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md). Please report security problems privately, as described
in [SECURITY.md](SECURITY.md), not in public issues.

## Licence

MIT. See [LICENSE](LICENSE).

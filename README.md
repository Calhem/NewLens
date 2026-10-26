# NewsLens

An open-source, self-hostable tool for examining news reporting critically: what an article
states, what it implies, what evidence supports it, and how other publishers cover the same
event. All application data is stored in [TypeDB](https://typedb.com).

## Status: Milestone 1 (runnable foundation)

What works now:

- Submit an article URL in the web interface. It's validated and saved in TypeDB as an
  article with retrieval status `queued`, together with a queued analysis run.
- Saved articles are listed from the database and survive restarts.
- Health checks, configuration checks, automated tests and CI.

What does **not** exist yet: fetching articles, extracting text, claims, evidence, framing
analysis, cross-publisher comparison. Nothing is retrieved from the web and no AI model is
called. See [docs/milestone-0.md](docs/milestone-0.md) for the plan.

## Run it

Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running).

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
| `worker` | Background worker; for now it only reports how many runs are queued | none |
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
| `TYPEDB_ADDRESS` | `host:port` of TypeDB. `127.0.0.1:1731` for local development; Compose overrides it to `typedb:1729`. |
| `TYPEDB_USERNAME`, `TYPEDB_PASSWORD` | TypeDB login. The defaults are TypeDB CE's built-in `admin` / `password`. |
| `TYPEDB_DATABASE` | Database name, e.g. `newslens`. |

No API keys are needed yet. Model and search providers arrive in later milestones, and each
will be documented here with whether it costs money.

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
newslens/        Python package: settings, db, migrations, store, api, serve, worker
schema/          schema.tql (base schema) and migrations/ (numbered changes, applied once)
scripts/         reset_dev.py, npm-docker.sh
tests/           pytest suite
web/             React frontend, its Dockerfile and nginx.conf
docs/            plans and design documents
```

## Licence

MIT. See [LICENSE](LICENSE).

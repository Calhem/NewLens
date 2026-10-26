# Contributing to NewsLens

Thanks for your interest. NewsLens is in early development, so please open an issue to discuss
a change before starting large work.

## Setting up

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and
[uv](https://docs.astral.sh/uv/). Follow "Run it" and "Development" in the [README](README.md).
**You don't need an Anthropic API key to develop or to run the tests.**

```bash
docker compose up -d typedb    # the tests need the local TypeDB
uv run pytest
```

The tests create and delete their own `newslens-test-*` databases, use a local test web server
instead of real websites, and use a fake model client. A test fails if anything tries to create
a real Claude client.

## Ground rules

- **Never commit secrets.** `.env` is git-ignored; put example values in `.env.example` only.
- **TypeDB is the only database.** Don't add another persistent store (SQLite, Postgres,
  Redis...), even as a cache or job queue.
- **Tests come with every change** and must not call external services. Use the fake model
  (`tests/fake_claude.py`) and the local test sites (`tests/webserver.py`). Test articles are
  synthetic: don't copy real articles into the repository.
- **All model calls go through `newslens/llm.py`,** which reserves spend against the budget
  before anything is sent. A test enforces that no other module uses the Anthropic SDK.
- **All web fetching goes through `newslens/ingest/http.py`.** Never weaken a network-safety
  check to make a test pass; give the test its own policy instead.
- **Evidence before conclusions.** Anything shown as fact must trace to stored text. Model
  output is untrusted until validated, inferences are labelled as inferences, and nothing is
  invented (no guessed dates, sources or quotes).
- **TypeDB 3.x only.** Check TypeQL against the TypeDB 3 docs and run it against the real
  server. 2.x examples are not compatible.
- **Schema changes are new migration files** in `schema/migrations/`, numbered in order. Never
  edit an applied migration.
- **Keep the documentation true**: `docs/security.md`, `docs/limitations.md` and
  `docs/dependencies.md` describe what the code actually does.

## Pull requests

1. Keep each pull request to one change, with a clear description of what and why.
2. Make sure `uv run pytest` passes, and for frontend changes `npm run lint` and
   `npm run build` in `web/`.
3. Say what you tested, and anything you couldn't test.

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE), the same licence as the project.

## Reporting bugs and security issues

- Bugs and ideas: open an issue.
- **Security vulnerabilities: don't open a public issue.** See [SECURITY.md](SECURITY.md).

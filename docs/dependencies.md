# Dependencies and why

Licences were checked on PyPI / npm on 2026-10-26. All are compatible with NewsLens's MIT licence.

## Python (pyproject.toml)

| Package | Licence | Why |
|---|---|---|
| typedb-driver 3.14.0 | Apache-2.0 | The official TypeDB driver, matching server 3.14.1. |
| fastapi, pydantic, pydantic-settings, uvicorn | MIT / BSD | API, validated models and settings, server. |
| httpcore 1.0 | BSD-3-Clause | Low-level HTTP used by the fetcher, so each connection can be checked (netsafe.py). |
| trafilatura 2.3 | Apache-2.0 | Main-text and link extraction. Its date detection is NOT used: it invents a date when a page has none. |
| protego | BSD-3-Clause | robots.txt parsing. |
| defusedxml | PSF | Safe XML parsing (refuses entity-expansion attacks). |
| anthropic 2.3 | Apache-2.0 | Claude SDK, used only in `newslens/llm.py`. |
| Dev: pytest, httpx2 | MIT / BSD-3-Clause | Tests. |

### The `httpx2` decision (2026-10-26)

FastAPI's test client warned: "Using `httpx` with `starlette.testclient` is deprecated; install
`httpx2` instead." Before switching we checked that `httpx2` is the genuine successor, not a
look-alike package:

- It is published by Tom Christie, the author of both `httpx` and Starlette, from the
  `pydantic/httpx2` repository, under BSD-3-Clause.
- Starlette's own release notes add it deliberately: 1.2.0 "Support httpx2 in the test client",
  1.3.0 "Add `httpx2` to the `full` extra". Starlette's `full` extra lists it.
- The Anthropic SDK 1.x+ is also built on it.

So the fix is to replace the test-only dependency `httpx` with `httpx2`, not to silence the
warning. Deprecation warnings now fail the test suite (`pyproject.toml`), so the next one is
noticed immediately.

## Frontend (web/package.json)

React 19, Vite 8, TypeScript 6 (the version the official Vite template pins), Tailwind CSS 4,
shadcn/ui components (copied into `src/components/ui/` and owned by this project), Radix UI
primitives (`radix-ui`), `lucide-react` icons, oxlint.

### The `cn` package (checked 2026-10-26)

shadcn 4 replaced its old `lib/utils.ts` helper with an npm package named `cn`. Because the
name is short and generic, we checked it: it is maintained by `shadcn`, published from the
`shadcn-ui/cn` repository, MIT licensed, and has no install-time scripts.

## Docker images (pinned)

`typedb/typedb:3.14.1`, `python:3.13.17-slim`, `ghcr.io/astral-sh/uv:0.13.5`,
`node:24.22.1-alpine`, `nginxinc/nginx-unprivileged:1.31.7-alpine` (runs nginx as non-root).

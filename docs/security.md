# Security and responsible operation

What NewsLens does today to stay safe, and what it does not do yet. Every point here is
implemented and covered by a test unless it says otherwise.

## Fetching web pages (Milestone 2)

Article URLs come from users and are untrusted. A malicious address could try to make the
server fetch something private ("server-side request forgery", SSRF). Every fetch goes through
`newslens/ingest/http.py` and `newslens/ingest/netsafe.py`:

| Safeguard | How |
|---|---|
| Only ordinary web addresses | `http://` or `https://`, ports 80 and 443 only, no user name or password in the address, at most 2,048 characters, no spaces or control characters. |
| Only public website names | Raw IP addresses (in any notation, including `2130706433` and `0x7f000001`), single-word names (`localhost`, `intranet`) and internal or reserved endings (`.internal`, `.local`, `.lan`, `.home`, `.corp`, `.arpa`, `.test`, `.example`, `.invalid`, `.onion`...) are refused before any network activity. |
| Only public addresses, checked when connecting | Each connection resolves the name itself and refuses the whole host if ANY address is private, loopback, link-local (including cloud metadata at 169.254.169.254), multicast, reserved, shared (100.64.0.0/10), or an IPv4 address hidden inside IPv6. It then connects to the address it checked, so a DNS answer can't change in between ("DNS rebinding"). |
| Redirects checked hop by hop | Redirects are followed by hand, at most 5, and every hop passes the same name and address checks. Loops are detected. Redirects to other websites are allowed (news links often use them), but the target site's robots.txt is checked before its content is used. |
| Size and time limits | 5 MB per page, 5 s to connect, 10 s per read, 30 s for the whole fetch including redirects. Compression is never requested, so the size limit applies to what is actually read. Extracted text is cut at 100,000 characters (marked "partial"). |
| Politeness | At most one request per 10 seconds to any website, shared across processes. Fetches only pages users submit (no crawling). Respects robots.txt; an unreadable robots.txt means "no permission". |
| Access controls respected | HTTP 401/403 → "not permitted", 402 → "paywalled"; pages marking themselves as not free are labelled as possibly a preview. NewsLens never tries to get around a paywall or login, and suggests pasting the text instead. |
| AI processing permission | Text is sent to an AI model only if robots.txt allows Anthropic's crawlers, has no `Content-Signal: ai-input=no`, and the page has no `noai` / `tdm-reservation` signal. Otherwise the claims stage is skipped and says why. |

Verified live (2026-10-26) through the running app: `localtest.me` (→ 127.0.0.1),
`169.254.169.254.nip.io` and `10.0.0.1.nip.io` were refused at connection time with no request
sent; `127.0.0.1`, `[::ffff:169.254.169.254]` and `metadata.google.internal` were refused at
submission.

## Untrusted text and model output

- **Prompt injection.** The article reaches the model only between `<article>` tags, and the
  system prompt says anything inside is material to analyse, never instructions. The model has
  no tools: it cannot fetch URLs or run anything. Its answer must match a fixed JSON schema.
- **Model output is validated before it is stored.** Every claim must quote a passage found
  verbatim in the article (otherwise it is discarded, and the discard is recorded), kinds and
  bases come from fixed lists, lengths are capped, and a speaker is kept only if the name
  appears in the article. Malformed answers store nothing; the article itself is kept.
- **Display.** The interface renders article text as plain text, never as HTML. Article links
  are clickable only if they are `http(s)://` and open with `rel="noopener noreferrer nofollow"`.
  nginx sends a strict Content-Security-Policy.

## Credentials and configuration

- Settings are checked at startup; problems are named in plain words. Secrets are `SecretStr`
  and never logged or returned by the API.
- **TypeDB password.** TypeDB CE starts with `admin` / `password`. That is accepted only with
  `NEWSLENS_ENVIRONMENT=development`, where every port is bound to 127.0.0.1. With
  `production`, NewsLens refuses to start unless the password is changed and at least 16
  characters. `uv run python -m scripts.set_typedb_password` generates a 32-character random
  password, sets it on the server and writes it to `.env` (permissions 600) without showing it.
  TypeDB CE has no per-user permissions (any user can see every database), so a separate
  "application user" would not add protection; a strong admin password is the control.
- **Model spending.** No model is called unless `NEWSLENS_MODEL_PROVIDER=anthropic`, an
  `ANTHROPIC_API_KEY` is set, AND a spending limit is set in TypeDB
  (`scripts.set_budget`). Each call reserves its maximum possible cost first and is refused if
  that would pass the limit. No model fallback is configured, because a fallback could run a
  different, differently priced model that the reservation can't bound.

## Not yet in place (needed before any shared deployment)

- No user accounts or access control: anyone who can reach the web port can submit articles
  and spend the model budget. The port is bound to 127.0.0.1 for this reason.
- No TLS. A shared deployment needs a reverse proxy with HTTPS and authentication.
- No per-user rate limit on submissions (each fetch is rate-limited per website).
- No automatic deletion: article text is kept until the database is reset. See retention below.

## Retention

NewsLens stores the extracted text of each article it analyses, because quotes and claims are
checked against it. It is kept in your own TypeDB database only, never shared or exported.
To delete everything: `uv run python -m scripts.reset_dev` or `docker compose down -v`.
Test fixtures are synthetic; no third-party article text is committed to the repository.

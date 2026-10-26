# Security policy

## Reporting a vulnerability

**Please don't report security problems in public issues, pull requests or discussions.**

Report them privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability**. That creates a private advisory that only the maintainers can see.

Please include:
- what the problem is and what an attacker could do with it
- the steps to reproduce it, or a proof of concept
- the version or commit you tested
- any ideas you have for fixing it

Please don't include real API keys, passwords or other people's data in a report. If you need
to show one, describe it or use a made-up value.

This is a small project maintained on a best-effort basis. We'll acknowledge reports as soon as
we can, keep you informed, and credit you when a fix is released, unless you'd rather not be
named. Please give us a reasonable time to fix a problem before disclosing it publicly.

## Supported versions

NewsLens is in early development with no releases yet. Only the latest code on the `main`
branch is supported.

## Things worth knowing

- **NewsLens is built to run on one computer.** It has no user accounts and no HTTPS; every
  port is bound to 127.0.0.1. Anyone who can reach the web port can submit articles and use
  the model budget. Don't expose it to a network without a reverse proxy that adds HTTPS and
  authentication. See [docs/security.md](docs/security.md) for what is and isn't in place.
- **In scope:** server-side request forgery through the article fetcher (reaching private
  networks, cloud metadata, or other internal addresses, including through redirects or DNS
  tricks), prompt injection that gets unvalidated model output stored, bypassing the model
  spending cap, injection into database queries, script execution through article content in
  the interface, and leaking secrets through logs or API responses.
- **Out of scope:** denial of service against the local development server, and anything that
  needs an attacker to already control the computer NewsLens runs on.

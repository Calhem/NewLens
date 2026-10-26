"""A local test web server that pretends to be several news websites (by Host header).

Tests never touch real sites. Made-up host names (courier.news, wire.news...) are "resolved"
to 127.0.0.1 by a test resolver, and the fetcher is given a policy that allows 127.0.0.1 and
this server's port only. Every article here is synthetic, written for the tests.

Adapted from Charcoal's tests/webserver.py (same author).
"""

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from newslens.ingest.http import FetchConfig, HostRateLimiter
from newslens.ingest.netsafe import AddressPolicy

TEST_HOSTS = {"courier.news", "www.courier.news", "wire.news", "short.link", "evil.news"}


@dataclass
class Route:
    status: int = 200
    body: bytes = b""
    headers: dict = field(default_factory=lambda: {"Content-Type": "text/html; charset=utf-8"})
    delay: float = 0.0
    drip: float = 0.0          # seconds between 1-byte chunks, to make a slow response


class Site:
    def __init__(self):
        self.routes, self.log = {}, []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                host = (self.headers.get("Host") or "").split(":")[0]
                site.log.append((time.time(), host, self.path))
                route = site.routes.get((host, self.path), Route(404, b"not found"))
                if route.delay:
                    time.sleep(route.delay)
                try:
                    self.send_response(route.status)
                    for k, v in route.headers.items():
                        self.send_header(k, v)
                    if not route.drip:
                        self.send_header("Content-Length", str(len(route.body)))
                    self.end_headers()
                    if route.drip:
                        for byte in route.body:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(route.drip)
                    else:
                        self.wfile.write(route.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, host, path="/"):
        return f"http://{host}:{self.port}{path}"

    def add(self, host, path, body=b"", status=200, content_type="text/html; charset=utf-8", **kw):
        headers = {"Content-Type": content_type, **kw.pop("headers", {})}
        self.routes[(host, path)] = Route(status, body if isinstance(body, bytes) else body.encode(),
                                          headers, **kw)

    def requested(self, host=None):
        return [(h, p) for _, h, p in self.log if host is None or h == host]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_resolver(host):
    if host in TEST_HOSTS:
        return ["127.0.0.1"]
    raise OSError(f"unknown test host {host}")


def test_config(site, lock_dir, **overrides):
    values = dict(min_interval=0.05, allow_fast=True, lock_dir=Path(lock_dir),
                  policy=AddressPolicy(allowed_ports=frozenset({site.port}),
                                       test_addresses=frozenset({"127.0.0.1"})),
                  resolver=test_resolver, connect_timeout=2, read_timeout=2, total_timeout=5,
                  max_bytes=200_000)
    values.update(overrides)
    return FetchConfig(**values)


ARTICLE_HEAD = """<meta property="og:title" content="Bridge to close for two years">
<meta property="og:site_name" content="The Courier (synthetic test site)">
<meta name="description" content="Council says repairs to the river bridge will take two years.">
<script type="application/ld+json">{"@type":"NewsArticle","author":{"@type":"Person","name":"Jane Writer"},
"datePublished":"2026-10-20T09:00:00+01:00"}</script>"""

ARTICLE_BODY = """<h1>Bridge to close for two years</h1>
<p>The council said on Monday that the river bridge will close in March for repairs.
“We have no choice but to close it,” said council leader Ann Lee.</p>
<p>Traffic will be diverted along the ring road, according to
<a href="https://council.gov.example/notice">a council notice</a>, while engineers replace the deck.</p>
<p>Local businesses said they feared losing customers during the closure, which the council
estimates will cost 40 million pounds in total.</p>
<p>"It is a disaster for the high street," said shop owner Tom Reed, who has traded there for
twenty years and says footfall has already fallen since the plans were announced.</p>"""


def article_page(head=ARTICLE_HEAD, body=ARTICLE_BODY, title="Bridge to close | The Courier"):
    return (f"<!doctype html><html lang='en'><head><title>{title}</title>{head}</head><body>"
            f"<nav><a href='/'>Home</a></nav><main><article>{body}</article></main></body></html>")


def build_courier(site, robots="User-agent: *\nAllow: /\n"):
    site.add("courier.news", "/robots.txt", robots, content_type="text/plain")
    site.add("courier.news", "/2026/bridge", article_page())


def hammer_limiter(lock_dir, interval, host, count, out_queue):
    """Run in a separate process: take `count` turns at the rate limiter and report times."""
    limiter = HostRateLimiter(lock_dir, interval)
    for _ in range(count):
        limiter.wait(host)
        out_queue.put(time.time())

"""One polite, bounded HTTP GET, following redirects by hand so each hop is checked.

Every hop (the first URL and each redirect target) must pass check_url, which needs no
network, and every connection must pass netsafe's address check at the moment of connecting.
Limits: at most `max_redirects` hops, `max_bytes` of body, per-step timeouts, and a total
deadline for the whole fetch including redirects. Requests to one host are spaced out by a
rate limiter that works across threads and processes on this machine. No compression is
requested, so the byte limit applies to what is actually read (no "zip bombs").

Adapted from Charcoal's charcoal/collect/fetch.py (same author). The difference: news links
often redirect to another website (short links, syndication), so redirects to other hosts are
allowed, but only to names that pass check_url and addresses that pass netsafe.
"""

import fcntl
import hashlib
import ipaddress
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpcore

from newslens.ingest.netsafe import STRICT, AddressPolicy, BlockedAddress, SafeBackend, system_resolver

USER_AGENT = "NewsLensBot/0.1 (self-hosted article analysis; fetches only user-submitted URLs)"
MIN_INTERVAL = 10.0
ACCEPT = "text/html,application/xhtml+xml;q=0.9"
MAX_URL_LENGTH = 2048

# Name endings that never belong to a public news website: special-use and internal names.
RESERVED_SUFFIXES = frozenset({"localhost", "local", "internal", "intranet", "lan", "home",
                               "corp", "private", "arpa", "invalid", "test", "example", "onion"})


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str = USER_AGENT
    min_interval: float = MIN_INTERVAL     # seconds between requests to one host
    max_redirects: int = 5
    max_bytes: int = 5_000_000             # news pages are large; text is limited separately
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    total_timeout: float = 30.0            # whole fetch, all redirects included
    dns_timeout: float = 5.0
    policy: AddressPolicy = STRICT
    resolver: object = system_resolver
    lock_dir: Path = Path("data/host-locks")
    allow_fast: bool = False               # tests only: permits min_interval below 10 s

    def __post_init__(self):
        if self.min_interval < MIN_INTERVAL and not self.allow_fast:
            raise ValueError("min_interval may not be below 10 seconds")


@dataclass
class Response:
    requested_url: str
    final_url: str
    status: int | None = None
    content_type: str | None = None
    headers: dict = field(default_factory=dict)
    body: bytes | None = None
    error: str | None = None
    redirects: list = field(default_factory=list)

    @property
    def ok(self):
        return self.error is None and self.status is not None and 200 <= self.status < 300


class HostRateLimiter:
    """At most one request per `interval` seconds to each host, shared by every thread and
    process on this machine through a lock file per host."""

    def __init__(self, lock_dir, interval):
        self.lock_dir, self.interval = Path(lock_dir), interval
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def wait(self, host):
        path = self.lock_dir / hashlib.sha256(host.lower().encode()).hexdigest()
        with open(path, "a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)          # waiters queue here, one at a time
            try:
                handle.seek(0)
                text = handle.read().strip()
                last = float(text) if text else 0.0
                delay = last + self.interval - time.time()
                if delay > 0:
                    time.sleep(delay)
                handle.seek(0)
                handle.truncate()
                handle.write(repr(time.time()))
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def check_host(host):
    """Is this a plausible public website name? Returns an error message or None.

    Refuses IP addresses in any notation, single-word names (localhost, intranet hosts) and
    reserved or internal endings. netsafe still checks the address the name resolves to."""
    if not host:
        return "no website name in the address"
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host.strip("[]"))
        return "addresses must use a website name, not an IP address"
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) < 2 or not all(labels):
        return "the address needs a full website name, such as example.com"
    if not labels[-1].isalpha() and not labels[-1].startswith("xn--"):
        return "addresses must use a website name, not an IP address"
    if labels[-1] in RESERVED_SUFFIXES:
        return f"names ending in .{labels[-1]} are internal or reserved"
    return None


def check_url(url, policy=STRICT):
    """Checks that need no network. Returns an error message or None."""
    if len(url) > MAX_URL_LENGTH:
        return f"the address is longer than {MAX_URL_LENGTH} characters"
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return "the address contains spaces or control characters"
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return "the address must start with http:// or https://"
    if parts.username or parts.password:
        return "addresses with a user name or password in them are not accepted"
    problem = check_host(parts.hostname)
    if problem:
        return problem
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return "the address has an invalid port"
    if port not in policy.allowed_ports:
        return f"port {port} is not allowed"
    return None


class Fetcher:
    def __init__(self, config=FetchConfig()):
        self.config = config
        self.limiter = HostRateLimiter(config.lock_dir, config.min_interval)
        backend = SafeBackend(policy=config.policy, resolver=config.resolver,
                              dns_timeout=config.dns_timeout)
        # No kept-alive connections: every request opens (and checks) a fresh connection.
        self.pool = httpcore.ConnectionPool(network_backend=backend, max_connections=4,
                                            max_keepalive_connections=0, retries=0)

    def close(self):
        self.pool.close()

    def get(self, url):
        """GET `url`, following redirects that pass the same checks. Never raises for network
        problems: they are returned in Response.error."""
        c = self.config
        result = Response(requested_url=url, final_url=url)
        deadline = time.monotonic() + c.total_timeout
        current, seen = url, {url}
        for _ in range(c.max_redirects + 1):
            problem = check_url(current, c.policy)
            if problem:
                result.error = problem if current == url else f"redirect refused: {problem}"
                return result
            host = urlsplit(current).hostname
            self.limiter.wait(host)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result.error = "took too long in total"
                return result
            timeouts = {"connect": min(c.connect_timeout, remaining),
                        "read": min(c.read_timeout, remaining),
                        "write": min(c.read_timeout, remaining), "pool": min(5.0, remaining)}
            try:
                with self.pool.stream("GET", current, headers=[
                        (b"User-Agent", c.user_agent.encode()), (b"Accept", ACCEPT.encode()),
                        (b"Accept-Encoding", b"identity")],
                        extensions={"timeout": timeouts}) as response:
                    headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                               for k, v in response.headers}
                    result.final_url, result.status, result.headers = current, response.status, headers
                    result.content_type = headers.get("content-type")
                    if 300 <= response.status < 400 and "location" in headers:
                        target = urljoin(current, headers["location"]).split("#")[0]
                        if target in seen:
                            result.error = "redirect loop"
                            return result
                        seen.add(target)
                        result.redirects.append(target)
                        current = target
                        continue
                    body, size = [], 0
                    for chunk in response.iter_stream():
                        size += len(chunk)
                        if size > c.max_bytes:
                            result.error = f"page larger than {c.max_bytes} bytes"
                            return result
                        if time.monotonic() > deadline:
                            result.error = "took too long in total"
                            return result
                        body.append(chunk)
                    result.body = b"".join(body)
                    if not 200 <= response.status < 300:
                        result.error = f"HTTP {response.status}"
                    return result
            except BlockedAddress as error:
                result.error = f"blocked: {error}"
            except httpcore.TimeoutException:
                result.error = "timed out"
            except httpcore.ConnectError as error:
                result.error = f"could not connect: {error}"
            except (httpcore.ProtocolError, httpcore.NetworkError, httpcore.UnsupportedProtocol) as error:
                result.error = f"invalid response: {type(error).__name__}"
            return result
        result.error = f"more than {c.max_redirects} redirects"
        return result

"""The fetcher against a local test web server: network safety, redirects, limits and
politeness. No real websites are contacted."""

import itertools
import multiprocessing
import threading

import pytest

import webserver as ws
from newslens.ingest.http import Fetcher
from newslens.ingest.netsafe import AddressPolicy, system_resolver


@pytest.fixture
def site():
    s = ws.Site()
    yield s
    s.close()


@pytest.fixture
def fetcher(site, tmp_path):
    f = Fetcher(ws.test_config(site, tmp_path))
    yield f
    f.close()


def test_a_page_is_fetched(site, fetcher):
    ws.build_courier(site)
    r = fetcher.get(site.url("courier.news", "/2026/bridge"))
    assert r.ok and b"Bridge to close" in r.body and r.redirects == []


def test_redirects_are_followed_across_sites_and_recorded(site, fetcher):
    ws.build_courier(site)
    site.add("short.link", "/abc", status=301,
             headers={"Location": site.url("courier.news", "/2026/bridge")})
    r = fetcher.get(site.url("short.link", "/abc"))
    assert r.ok and r.final_url == site.url("courier.news", "/2026/bridge")
    assert r.redirects == [r.final_url]


@pytest.mark.parametrize("target", [
    "http://169.254.169.254/latest/meta-data/", "http://localhost:{port}/",
    "http://127.0.0.1:{port}/", "http://[::1]:{port}/", "http://[::ffff:127.0.0.1]:{port}/",
    "http://2130706433:{port}/", "http://0x7f000001:{port}/", "file:///etc/passwd",
    "http://metadata.google.internal/", "http://printer.local:{port}/", "http://intranet:{port}/",
    "https://courier.news:8443/", "http://user:pw@courier.news:{port}/",  # pragma: allowlist secret
])
def test_redirects_to_internal_or_odd_destinations_are_refused(site, fetcher, target):
    site.add("courier.news", "/go", status=302, headers={"Location": target.format(port=site.port)})
    r = fetcher.get(site.url("courier.news", "/go"))
    assert r.error and r.error.startswith("redirect refused") and r.body is None
    assert site.requested() == [("courier.news", "/go")]              # nothing else contacted


def test_internal_addresses_are_refused_when_connecting(site, tmp_path):
    """Without the test exception, a name that resolves to 127.0.0.1 is refused."""
    site.add("courier.news", "/", "secret")
    strict = AddressPolicy(allowed_ports=frozenset({site.port}))
    f = Fetcher(ws.test_config(site, tmp_path, policy=strict))
    r = f.get(site.url("courier.news"))
    assert r.error.startswith("blocked:") and "not a public internet address" in r.error
    assert site.requested() == []
    for url in ("http://localhost:{p}/", "http://127.0.0.1:{p}/", "http://[::1]:{p}/",
                "http://0x7f000001:{p}/", "http://2130706433:{p}/"):
        f2 = Fetcher(ws.test_config(site, tmp_path, policy=strict, resolver=system_resolver))
        assert f2.get(url.format(p=site.port)).error, url
        f2.close()
    assert site.requested() == []
    f.close()


def test_dns_rebinding_is_caught_on_every_connection(site, tmp_path):
    site.add("courier.news", "/", "hello")
    answers = itertools.cycle([["127.0.0.1"], ["10.0.0.7"]])
    f = Fetcher(ws.test_config(site, tmp_path, resolver=lambda host: next(answers)))
    assert f.get(site.url("courier.news")).ok                          # first answer: allowed
    second = f.get(site.url("courier.news"))                           # same name, new answer
    assert second.error.startswith("blocked:")
    assert len(site.requested()) == 1
    mixed = Fetcher(ws.test_config(site, tmp_path, resolver=lambda h: ["127.0.0.1", "192.168.0.9"]))
    assert mixed.get(site.url("courier.news")).error.startswith("blocked:")
    f.close(); mixed.close()


def test_a_redirect_to_a_name_resolving_inside_is_refused(site, tmp_path):
    """Redirect targets are checked at connection time like the first URL."""
    site.add("courier.news", "/go", status=302, headers={"Location": site.url("evil.news", "/x")})
    resolver = lambda host: ["127.0.0.1"] if host == "courier.news" else ["10.1.2.3"]
    f = Fetcher(ws.test_config(site, tmp_path, resolver=resolver))
    r = f.get(site.url("courier.news", "/go"))
    assert r.error.startswith("blocked:") and site.requested() == [("courier.news", "/go")]
    f.close()


def test_redirect_loops_and_long_chains_stop(site, fetcher):
    site.add("courier.news", "/a", status=302, headers={"Location": "/b"})
    site.add("courier.news", "/b", status=302, headers={"Location": "/a"})
    assert fetcher.get(site.url("courier.news", "/a")).error == "redirect loop"
    for i in range(8):
        site.add("courier.news", f"/hop{i}", status=302, headers={"Location": f"/hop{i + 1}"})
    assert fetcher.get(site.url("courier.news", "/hop0")).error == "more than 5 redirects"


def test_timeouts_and_size_limits(site, tmp_path):
    site.add("courier.news", "/slow", "late", delay=3)
    site.add("courier.news", "/drip", "x" * 100, drip=0.05)
    site.add("courier.news", "/big", "x" * 50_000)
    f = Fetcher(ws.test_config(site, tmp_path, read_timeout=0.5, total_timeout=1.5, max_bytes=10_000))
    assert f.get(site.url("courier.news", "/slow")).error == "timed out"
    assert f.get(site.url("courier.news", "/drip")).error == "took too long in total"
    assert f.get(site.url("courier.news", "/big")).error == "page larger than 10000 bytes"
    f.close()


def test_compression_is_never_requested(site, fetcher):
    seen = {}
    original = site.server.RequestHandlerClass.do_GET
    def spy(handler):
        seen["accept-encoding"] = handler.headers.get("Accept-Encoding")
        original(handler)
    site.server.RequestHandlerClass.do_GET = spy
    site.add("courier.news", "/", "ok")
    fetcher.get(site.url("courier.news"))
    assert seen["accept-encoding"] == "identity"


def test_requests_to_one_host_are_spaced_out(site, tmp_path):
    ws.build_courier(site)
    f = Fetcher(ws.test_config(site, tmp_path, min_interval=0.3))
    for _ in range(4):
        f.get(site.url("courier.news", "/2026/bridge"))
    times = [t for t, h, _ in site.log if h == "courier.news"]
    # Measured at the server, so allow 50 ms of thread-scheduling jitter on a 0.3 s interval.
    assert len(times) == 4 and min(b - a for a, b in zip(times, times[1:])) >= 0.25
    f.close()


def test_spacing_holds_across_threads(site, tmp_path):
    ws.build_courier(site)
    def job():
        f = Fetcher(ws.test_config(site, tmp_path, min_interval=0.3))
        for _ in range(3):
            f.get(site.url("courier.news", "/2026/bridge"))
        f.close()
    threads = [threading.Thread(target=job) for _ in range(2)]
    for t in threads: t.start()
    for t in threads: t.join()
    times = sorted(t for t, h, _ in site.log if h == "courier.news")
    assert len(times) == 6 and min(b - a for a, b in zip(times, times[1:])) >= 0.25


def test_spacing_holds_across_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    procs = [ctx.Process(target=ws.hammer_limiter, args=(str(tmp_path), 0.3, "courier.news", 3, queue))
             for _ in range(2)]
    for p in procs: p.start()
    times = sorted(queue.get(timeout=30) for _ in range(6))
    for p in procs: p.join()
    assert min(b - a for a, b in zip(times, times[1:])) >= 0.25

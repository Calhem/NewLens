"""Ingestion rules that need no network: addresses, URLs, robots and extraction."""

import pytest

from newslens.ingest.extract import (MAX_TEXT_CHARS, Article, decode, extract_article,
                                     find_quotes, header_opt_out, with_text)
from newslens.ingest.http import FetchConfig, check_url
from newslens.ingest.netsafe import STRICT, prohibited
from newslens.ingest.robots import SiteRules
from webserver import ARTICLE_BODY, article_page

UA = "NewsLensBot/0.1"


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "127.8.8.8", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "100.64.0.1", "0.0.0.0", "224.0.0.1", "239.255.255.250", "255.255.255.255", "240.0.0.1",
    "198.18.0.1", "192.0.2.1", "::1", "::", "fe80::1", "fc00::1", "fd00:ec2::254", "ff02::1",
    "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:10.0.0.1", "2002:7f00:1::1",
    "2002:a9fe:a9fe::1", "64:ff9b::a00:1", "2001:db8::1",
])
def test_prohibited_addresses(ip):
    assert prohibited(ip)


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert not prohibited(ip)


def test_the_default_policy_is_strict():
    assert STRICT.test_addresses == frozenset()
    assert STRICT.allowed_ports == frozenset({80, 443})
    assert FetchConfig().policy == STRICT
    with pytest.raises(ValueError):
        FetchConfig(min_interval=1)          # politeness can't be relaxed outside tests


@pytest.mark.parametrize("url, reason", [
    ("ftp://courier.news/", "http:// or https://"), ("file:///etc/passwd", "http:// or https://"),
    ("javascript:alert(1)", "http:// or https://"), ("courier.news/story", "http:// or https://"),
    ("http://courier.news:8080/", "port 8080"), ("https://user:pw@courier.news/", "user name"),  # pragma: allowlist secret
    ("http:///x", "no website name"), ("http://localhost/", "full website name"),
    ("http://127.0.0.1/", "not an IP address"), ("http://[::1]/", "not an IP address"),
    ("http://2130706433/", "full website name"), ("http://10.0.0.1.nip/", None),
    ("http://metadata.google.internal/", ".internal"), ("http://router.lan/", ".lan"),
    ("http://site.test/", ".test"), ("https://courier.news/a b", "spaces"),
    ("https://courier.news/" + "a" * 2100, "longer than"),
])
def test_urls_that_are_never_fetched(url, reason):
    problem = check_url(url, STRICT)
    if reason is None:                       # a public-looking name: allowed by the name check;
        assert problem is None               # netsafe checks where it really points
    else:
        assert problem and reason in problem


@pytest.mark.parametrize("url", ["https://courier.news/2026/bridge", "http://www.bbc.co.uk/news",
                                 "https://xn--bcher-kva.example.de/x", "https://news.example.com:443/a?b=c"])
def test_ordinary_news_urls_pass(url):
    assert check_url(url, STRICT) is None


def test_robots_rules_for_fetching_and_ai():
    url = "https://courier.news/2026/bridge"
    open_rules = SiteRules(UA, "User-agent: *\nAllow: /\n")
    assert open_rules.may_fetch(url).allowed and open_rules.may_send_to_ai(url).allowed
    assert not SiteRules(UA, "User-agent: *\nDisallow: /2026/\n").may_fetch(url).allowed
    ai = SiteRules(UA, "User-agent: *\nAllow: /\n\nUser-agent: ClaudeBot\nDisallow: /\n")
    assert ai.may_fetch(url).allowed and not ai.may_send_to_ai(url).allowed
    assert "ClaudeBot" in ai.may_send_to_ai(url).reason
    signal = SiteRules(UA, "User-agent: *\nContent-Signal: search=yes, ai-input=no\nAllow: /\n")
    assert signal.may_fetch(url).allowed and not signal.may_send_to_ai(url).allowed
    blocked = SiteRules(UA, blocked_reason="robots.txt unavailable")
    assert not blocked.may_fetch(url).allowed and not blocked.may_send_to_ai(url).allowed


def test_metadata_comes_only_from_explicit_sources():
    a = extract_article(article_page().encode(), "text/html; charset=utf-8", "https://courier.news/2026/bridge")
    assert a.error is None
    assert a.headline == "Bridge to close for two years"
    assert a.authors == ["Jane Writer"] and a.publisher_name.startswith("The Courier")
    assert a.published_at == "2026-10-20T08:00:00Z" and a.modified_at is None
    assert "published-at: JSON-LD datePublished" in a.sources
    assert "authors: JSON-LD author" in a.sources
    assert a.language == "en" and not a.paywalled and not a.truncated


def test_no_date_is_invented_when_the_page_has_none():
    bare = article_page(head="", body=ARTICLE_BODY.replace("on Monday", "this week"))
    a = extract_article(bare.encode(), "text/html", "https://courier.news/x")
    assert a.text and a.published_at is None and a.modified_at is None and a.authors == []
    assert not any(s.startswith("published-at") for s in a.sources)


def test_quotes_have_exact_offsets():
    a = extract_article(article_page().encode(), "text/html", "https://courier.news/x")
    quoted = [q.text for q in a.quotes]
    assert quoted == ["We have no choice but to close it,", "It is a disaster for the high street,"]
    assert all(a.text[q.start:q.end] == q.text for q in a.quotes)
    # One-word quotes are skipped, but they don't throw off the pairing of later marks.
    assert [q.text for q in find_quotes('He said "no" and "yes please" then “ ”.')] == ["yes please"]
    assert [q.text for q in find_quotes('“Not now,” she said. “Maybe later.”')] == ["Not now,", "Maybe later."]
    text = 'An odd "mark\nin one paragraph" is not paired across lines.'
    assert find_quotes(text) == []


def test_links_inside_the_article_are_kept_with_anchor_text():
    a = extract_article(article_page().encode(), "text/html", "https://courier.news/x")
    assert [(l.url, l.anchor_text) for l in a.links] == [
        ("https://council.gov.example/notice", "a council notice")]


def test_paywall_marker_and_ai_opt_outs_are_detected():
    paywall = '<script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script>'
    assert extract_article(article_page(head=paywall).encode(), "text/html", "https://c.news/").paywalled
    noai = extract_article(article_page(head='<meta name="robots" content="noai">').encode(),
                           "text/html", "https://c.news/")
    assert "noai" in noai.ai_opt_out
    assert header_opt_out({"x-robots-tag": "noai"}) and header_opt_out({"tdm-reservation": "1"})
    assert header_opt_out({}) is None


def test_long_text_is_cut_and_marked():
    article = with_text(Article(), "word " * (MAX_TEXT_CHARS // 2))
    assert article.truncated and len(article.text) == MAX_TEXT_CHARS


def test_bad_html_and_encodings_never_crash():
    for body in (b"", b"<<<>>>", b"\xff\xfe\x00garbage", b"<html><body><p>unclosed",
                 "café".encode("latin-1"), b"<html>" + b"<div>" * 5000,
                 b'<script type="application/ld+json">{not json</script>'):
        result = extract_article(body, "text/html; charset=utf-8", "https://courier.news/")
        assert result.text or result.error
    assert decode(b"caf\xe9", "text/html; charset=latin-1") == "café"
    assert decode(b"caf\xe9", "text/html; charset=no-such-charset") == "caf�"

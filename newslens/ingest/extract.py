"""Turning a fetched news page into an article: main text, metadata, quotations and links.

Rules:
- Metadata comes only from explicit machine-readable sources on the page (meta tags, JSON-LD,
  <link rel="canonical">, <html lang>), and every value records where it came from. Nothing
  is guessed: trafilatura's own date detection is NOT used, because it invents a date when a
  page has none.
- The main text comes from trafilatura. It is the text every offset and quote refers to.
- Quotations are found by their quotation marks, with exact offsets. Who said them is not
  decided here.
- Hyperlinks are the links inside the main text, with their anchor text.

Adapted in part from Charcoal's charcoal/collect/extract.py (same author).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin

import trafilatura
from defusedxml import ElementTree as SafeXML
from lxml import html as lxml_html

HTML_TYPES = ("text/html", "application/xhtml+xml")
MAX_TEXT_CHARS = 100_000      # longer articles are cut here and marked partial
MAX_LINKS = 200
_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([A-Za-z0-9_\-]+)""", re.IGNORECASE)
# “Curly” quotes have distinct opening and closing marks; "straight" ones are paired in order
# within a paragraph (1st with 2nd, 3rd with 4th...), so one short quote can't shift the rest.
_CURLY = re.compile(r"“([^”\n]{1,2000})”")
MAX_QUOTE_CHARS = 2000


@dataclass
class Quote:
    start: int                 # offsets of the quoted words (inside the marks) in the text
    end: int
    text: str


@dataclass
class Link:
    url: str
    anchor_text: str


@dataclass
class Article:
    text: str | None = None
    headline: str | None = None
    subheading: str | None = None
    authors: list = field(default_factory=list)
    publisher_name: str | None = None
    canonical_url: str | None = None
    published_at: str | None = None        # TypeQL datetime-tz literal
    modified_at: str | None = None
    language: str | None = None
    paywalled: bool = False
    truncated: bool = False
    quotes: list = field(default_factory=list)
    links: list = field(default_factory=list)
    sources: list = field(default_factory=list)   # "headline: meta og:title", ...
    ai_opt_out: str | None = None          # reason, if the page refuses AI processing
    error: str | None = None


def media_type(content_type):
    return (content_type or "").split(";")[0].strip().lower()


def decode(body, content_type):
    """Bytes to text: the declared charset, else a <meta charset>, else UTF-8. Bad bytes are
    replaced, never fatal."""
    match = re.search(r"charset=([A-Za-z0-9_\-]+)", content_type or "", re.IGNORECASE)
    charset = match.group(1) if match else None
    if not charset:
        meta = _META_CHARSET.search(body[:4096])
        charset = meta.group(1).decode("ascii", "ignore") if meta else "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:                     # an unknown charset name
        return body.decode("utf-8", errors="replace")


def header_opt_out(headers):
    """AI opt-outs sent as HTTP headers."""
    tag = headers.get("x-robots-tag", "").lower()
    if re.search(r"\bnoai\b", tag):
        return "the page's X-Robots-Tag header says noai"
    if headers.get("tdm-reservation", "").strip() == "1":
        return "the page reserves text-and-data-mining rights (TDM-Reservation: 1)"
    return None


def _json_ld(doc):
    """News/article objects from the page's JSON-LD blocks."""
    found = []
    for script in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(script)
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            kinds = item.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if any(isinstance(k, str) and ("Article" in k or k in ("Report", "BlogPosting")) for k in kinds):
                found.append(item)
    return found


def _datetime(value):
    """An ISO 8601 date/time as a UTC TypeQL literal, plus a note if no time zone was given."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None, None
    note = None
    if parsed.tzinfo is None:
        parsed, note = parsed.replace(tzinfo=timezone.utc), "no time zone given; read as UTC"
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"), note


def _first(doc, xpath):
    for value in doc.xpath(xpath):
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return None


def _names(value):
    """Author names from a JSON-LD author value (a string, an object, or a list of either)."""
    values = value if isinstance(value, list) else [value]
    names = []
    for v in values:
        name = v.get("name") if isinstance(v, dict) else v
        if isinstance(name, str) and name.strip():
            names.append(" ".join(name.split()))
    return names


def _metadata(doc, base_url, result):
    ld = _json_ld(doc)

    def take(field_name, candidates):
        for value, source in candidates:
            if value:
                setattr(result, field_name, value)
                result.sources.append(f"{field_name.replace('_', '-')}: {source}")
                return

    def ld_value(key):
        return next((item[key] for item in ld if isinstance(item.get(key), str) and item[key].strip()), None)

    take("headline", [(_first(doc, '//meta[@property="og:title"]/@content'), "meta og:title"),
                      (ld_value("headline"), "JSON-LD headline"),
                      (_first(doc, "//h1//text()"), "first <h1> heading"),
                      (_first(doc, "//title/text()"), "<title>")])
    take("subheading", [(_first(doc, '//meta[@property="og:description"]/@content'), "meta og:description"),
                        (_first(doc, '//meta[@name="description"]/@content'), "meta description")])
    take("publisher_name", [(_first(doc, '//meta[@property="og:site_name"]/@content'), "meta og:site_name"),
                            (next((p.get("name") for item in ld for p in [item.get("publisher")]
                                   if isinstance(p, dict) and isinstance(p.get("name"), str)), None),
                             "JSON-LD publisher")])
    canonical = _first(doc, '//link[@rel="canonical"]/@href')
    take("canonical_url", [(urljoin(base_url, canonical) if canonical else None, '<link rel="canonical">')])
    take("language", [(_first(doc, "/html/@lang"), "<html lang>")])

    ld_authors = [name for item in ld for name in _names(item.get("author"))]
    meta_authors = [" ".join(v.split()) for v in doc.xpath('//meta[@name="author"]/@content') if v.strip()]
    if ld_authors:
        result.authors, source = list(dict.fromkeys(ld_authors)), "JSON-LD author"
    elif meta_authors:
        result.authors, source = list(dict.fromkeys(meta_authors)), "meta author"
    if result.authors:
        result.sources.append(f"authors: {source}")

    for field_name, meta, key in (("published_at", "article:published_time", "datePublished"),
                                  ("modified_at", "article:modified_time", "dateModified")):
        for value, source in ((_first(doc, f'//meta[@property="{meta}"]/@content'), f"meta {meta}"),
                              (ld_value(key), f"JSON-LD {key}")):
            literal, note = _datetime(value) if value else (None, None)
            if literal:
                setattr(result, field_name, literal)
                result.sources.append(f"{field_name.replace('_', '-')}: {source}"
                                      + (f" ({note})" if note else ""))
                break

    if any(item.get("isAccessibleForFree") in (False, "False", "false") for item in ld):
        result.paywalled = True
        result.sources.append("paywall: JSON-LD isAccessibleForFree is false")


def find_quotes(text):
    """Every passage in double quotation marks of at least two words, with exact offsets."""
    spans = [(m.start(1), m.end(1)) for m in _CURLY.finditer(text)]
    offset = 0
    for line in text.split("\n"):
        marks = [offset + i for i, ch in enumerate(line) if ch == '"']
        spans += [(a + 1, b) for a, b in zip(marks[0::2], marks[1::2])]
        offset += len(line) + 1
    quotes = []
    for start, end in sorted(spans):
        inner = text[start:end]
        if len(inner.split()) >= 2 and len(inner) <= MAX_QUOTE_CHARS:
            quotes.append(Quote(start, end, inner))
    return quotes


def _links(xml_text, base_url):
    try:
        root = SafeXML.fromstring(xml_text)
    except Exception:                      # defusedxml also refuses entity tricks here
        return []
    links = []
    for ref in root.iter("ref"):
        target = (ref.get("target") or "").strip()
        if not target:
            continue
        url = urljoin(base_url, target).split("#")[0]
        if url.startswith(("http://", "https://")):
            links.append(Link(url, " ".join("".join(ref.itertext()).split())))
        if len(links) >= MAX_LINKS:
            break
    return links


def extract_article(body, content_type, url):
    """Extract an article from a fetched HTML page. Never raises: problems go in .error."""
    result = Article()
    html = decode(body, content_type)
    try:
        doc = lxml_html.fromstring(html)
    except Exception as error:              # lxml raises several types on hopeless input
        result.error = f"the page could not be parsed ({type(error).__name__})"
        return result
    robots_meta = " ".join(doc.xpath('//meta[@name="robots" or @name="ai"]/@content')).lower()
    if re.search(r"\bnoai\b", robots_meta):
        result.ai_opt_out = "the page's robots meta tag says noai"
    if "1" in [v.strip() for v in doc.xpath('//meta[@name="tdm-reservation"]/@content')]:
        result.ai_opt_out = "the page reserves text-and-data-mining rights (tdm-reservation meta tag)"
    _metadata(doc, url, result)
    try:
        # deduplicate stays off: trafilatura's dedup cache spans calls, so a rerun would
        # discard an unchanged page's text.
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True,
                                   deduplicate=False)
        xml = trafilatura.extract(html, url=url, include_comments=False, include_tables=True,
                                  deduplicate=False, output_format="xml", include_links=True)
    except Exception as error:
        result.error = f"text extraction failed ({type(error).__name__})"
        return result
    if not text or not text.strip():
        result.error = "no article text was found on the page"
        return result
    return with_text(result, text.strip(), links=_links(xml, url) if xml else [])


def with_text(result, text, links=()):
    """Attach the main text (cut to MAX_TEXT_CHARS), its quotations and links."""
    if len(text) > MAX_TEXT_CHARS:
        text, result.truncated = text[:MAX_TEXT_CHARS], True
    result.text = text
    result.quotes = find_quotes(text)
    result.links = list(links)
    return result

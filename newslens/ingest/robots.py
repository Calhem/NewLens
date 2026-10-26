"""May NewsLens fetch this page, and may its text be sent to an AI provider?

Two separate questions, both answered from the site's own signals:

- Fetching: robots.txt rules for NewsLens's user agent (falling back to `*`). NewsLens only
  fetches pages a user submitted, but it still respects a site's published rules.
- AI processing: claim extraction sends the article text to an AI provider, so that only
  happens if robots.txt also allows Anthropic's crawlers (ClaudeBot, anthropic-ai), robots.txt
  has no `Content-Signal: ai-input=no`, and the page itself doesn't opt out (see extract.py).
  Permission to fetch is never taken as permission for AI processing.

If robots.txt can't be read reliably (server error, timeout, access denied), the host is
treated as "no permission". Only a clean 404/410 means "no rules".

Adapted from Charcoal's charcoal/collect/robots.py (same author).
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from protego import Protego

AI_AGENTS = ("ClaudeBot", "anthropic-ai")
_SIGNAL = re.compile(r"^\s*content-signal\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


@dataclass
class Decision:
    allowed: bool
    reason: str


class SiteRules:
    def __init__(self, user_agent, text=None, blocked_reason=None, unsafe_address=None):
        self.user_agent = user_agent.split("/")[0]
        self.blocked_reason = blocked_reason
        # Set when the site's address is not on the public internet: nothing may be fetched,
        # and the reason is the address, not the site's rules.
        self.unsafe_address = unsafe_address
        self.rules = Protego.parse(text or "")
        self.ai_input_refused = any(
            re.search(r"(^|[\s,])ai-input\s*=\s*no\b", line, re.IGNORECASE)
            for line in _SIGNAL.findall(text or ""))

    def may_fetch(self, url):
        if self.blocked_reason:
            return Decision(False, self.blocked_reason)
        if not self.rules.can_fetch(url, self.user_agent):
            return Decision(False, "the site's robots.txt does not allow fetching this page")
        return Decision(True, "allowed by robots.txt")

    def may_send_to_ai(self, url):
        if self.blocked_reason:
            return Decision(False, self.blocked_reason)
        for agent in AI_AGENTS:
            if not self.rules.can_fetch(url, agent):
                return Decision(False, f"the site's robots.txt disallows {agent}, so the text "
                                       "can't be sent to an AI provider")
        if self.ai_input_refused:
            return Decision(False, "the site's robots.txt says ai-input=no")
        return Decision(True, "allowed by robots.txt")


def robots_url(page_url):
    parts = urlsplit(page_url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def load_rules(fetcher, page_url):
    """Fetch and interpret robots.txt for the host of `page_url`."""
    response = fetcher.get(robots_url(page_url))
    ua = fetcher.config.user_agent
    if response.error and response.error.startswith("blocked:"):
        return SiteRules(ua, blocked_reason=response.error,
                         unsafe_address=response.error.removeprefix("blocked:").strip())
    if response.status in (404, 410):
        return SiteRules(ua, "")
    if response.ok and response.body is not None:
        return SiteRules(ua, response.body.decode("utf-8", errors="replace"))
    if response.status in (401, 403):
        why = f"robots.txt access denied (HTTP {response.status}); treated as no permission"
    elif response.status is not None and 400 <= response.status < 500 and not response.error:
        return SiteRules(ua, "")
    else:
        why = f"robots.txt unavailable ({response.error or response.status}); treated as no permission"
    return SiteRules(ua, blocked_reason=why)

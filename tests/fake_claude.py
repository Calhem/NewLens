"""A fake Claude client for tests: scripted replies and errors, and a record of every request.
It never contacts Anthropic. Copied from Charcoal's tests (same author)."""

import json
import threading
from types import SimpleNamespace

import anthropic
import httpx2

_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def reply(data=None, text=None, stop="end_turn", input_tokens=1000, output_tokens=500):
    body = text if text is not None else json.dumps(data)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=body)], stop_reason=stop,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_creation_input_tokens=0, cache_read_input_tokens=0))


def http_error(status):
    return anthropic.APIStatusError(f"HTTP {status}", response=httpx2.Response(status, request=_REQUEST),
                                    body=None)


def timeout():
    return anthropic.APITimeoutError(request=_REQUEST)


class FakeClaude:
    def __init__(self, *script):
        self.script, self.requests = list(script), []
        self._lock = threading.Lock()
        self.messages = self

    def create(self, **request):
        with self._lock:
            self.requests.append(request)
            item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

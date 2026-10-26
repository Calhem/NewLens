"""The only place NewsLens talks to an AI model, and the hard spend cap that guards every call.

No other module may create a Claude client or import the SDK (a test enforces this).

Providers: `ModelProvider` is the interface the pipeline uses. `ClaudeProvider` is the first
implementation; tests use a fake client. With NEWSLENS_MODEL_PROVIDER=none (the default) there
is no provider and no model is ever called.

Spend control, for every request:
1. Work out the most the request could possibly cost: every byte of input counted as a token
   (a strict upper bound) plus the full output allowance, at the configured prices.
2. Reserve that amount in TypeDB against the global budget. Every reservation updates the
   ledger, so concurrent reservations from any process conflict inside TypeDB and one is
   retried against the new total. A reservation that would pass the limit is refused BEFORE
   anything is sent. A budget with no limit refuses everything: the limit is set only with
   scripts/set_budget.py, never from a process's settings.
3. Send the request (the SDK's own retries are off; ours are bounded and each one reserves).
4. Settle the reservation to the real cost from the usage the API reports. A request the API
   rejected outright is settled at zero. A timeout or unclear failure keeps its full
   reservation ("held") until someone reconciles it, because it may have been charged.

No model fallback is configured: a fallback could answer with a different model at a
different price, which the reservation can't bound. A refusal is recorded as a refusal.

Adapted from Charcoal's charcoal/llm.py (same author), with one global budget only.
"""

import json
import math
import secrets
import time
import tomllib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from typedb.driver import TransactionType, TypeDBDriverException

from newslens.db import atomically, now, string, tx_fetch

MODEL = "claude-opus-5-5"
PROVIDER = "anthropic"
PRICING_FILE = Path(__file__).parent.parent / "config" / "pricing.toml"
PRICING_MAX_AGE_DAYS = 45
GLOBAL_LEDGER = "model-spend"
MAX_OUTPUT_TOKENS = 16_000
MAX_INPUT_BYTES = 500_000
INPUT_OVERHEAD_TOKENS = 2_000            # system formatting and schema handling, generously
MAX_ATTEMPTS = 3
RESERVE_RETRIES = 25                     # attempts when concurrent ledger updates conflict
NOT_CHARGED = {400, 401, 403, 404, 409, 413, 422, 429, 529}   # rejected before any work
RETRYABLE = {429, 500, 502, 503, 504, 529}


class BudgetExceeded(Exception):
    """The call's maximum possible cost would take spend past the budget. Nothing was sent."""


class BudgetNotInitialised(BudgetExceeded):
    """The budget has no limit set yet; the owner must set one. Nothing was sent."""


class PricingOutOfDate(Exception):
    """config/pricing.toml hasn't been re-checked recently enough to trust."""


class CallFailed(Exception):
    """No usable answer. `held` says whether any reservation is still held as possibly charged."""
    def __init__(self, message, held=False):
        super().__init__(message)
        self.held = held


class ModelRefused(CallFailed):
    """The model declined the request (stop reason "refusal")."""


class BadOutput(CallFailed):
    """The answer was cut off or wasn't the requested JSON."""


class ModelProvider(Protocol):
    """What the analysis pipeline needs from a model provider."""
    provider: str
    model: str

    def structured(self, purpose, system, user_text, schema, max_tokens, prompt_version,
                   run_id=None) -> dict:
        """One request for JSON matching `schema`; returns the parsed JSON (not yet validated
        against the application's own rules: callers must do that)."""


@dataclass(frozen=True)
class Pricing:
    model: str
    input: Decimal                # USD per million tokens = micro-dollars per token
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal
    verified_on: date
    source: str


def load_pricing(model=MODEL, path=PRICING_FILE, today=None):
    with open(path, "rb") as f:
        entry = tomllib.load(f)["models"][model]
    pricing = Pricing(model, Decimal(entry["input_usd_per_mtok"]), Decimal(entry["output_usd_per_mtok"]),
                      Decimal(entry["cache_write_usd_per_mtok"]), Decimal(entry["cache_read_usd_per_mtok"]),
                      entry["verified_on"], entry["source"])
    age = ((today or date.today()) - pricing.verified_on).days
    if age > PRICING_MAX_AGE_DAYS:
        raise PricingOutOfDate(f"prices for {model} were last checked {age} days ago; re-check "
                               f"{pricing.source} and update {path.name}")
    return pricing


def max_cost_micros(pricing, input_bytes, max_tokens):
    """The most a request could cost, in micro-dollars, rounded up."""
    tokens_in = input_bytes + INPUT_OVERHEAD_TOKENS
    return math.ceil(tokens_in * pricing.input + max_tokens * pricing.output)


def actual_cost_micros(pricing, usage):
    """Real cost from the usage the API reported, rounded up."""
    get = lambda name: getattr(usage, name, 0) or 0
    return math.ceil(get("input_tokens") * pricing.input + get("output_tokens") * pricing.output
                     + get("cache_creation_input_tokens") * pricing.cache_write
                     + get("cache_read_input_tokens") * pricing.cache_read)


def usd(micros):
    return Decimal(micros) / 1_000_000


def _micros(usd_amount):
    return int(Decimal(str(usd_amount)) * 1_000_000)


def set_budget_limit(driver, db, limit_usd, warning_usd=None):
    """OWNER OPERATION: create the budget or set its limit (and warning level).

    The only way the limit is set; use scripts/set_budget.py. Committed spend is never changed.
    """
    limit = _micros(limit_usd)
    warning = _micros(warning_usd) if warning_usd is not None else limit
    if limit < 0 or warning < 0:
        raise ValueError("limits can't be negative")

    def work(tx):
        if not tx_fetch(tx, f'match $l isa budget-ledger, has ledger-id {string(GLOBAL_LEDGER)}; '
                            f'fetch {{ "id": $l.ledger-id }};'):
            tx.query(f'insert $l isa budget-ledger, has ledger-id {string(GLOBAL_LEDGER)}, '
                     f'has committed-micros 0;').resolve()
        tx.query(f'match $l isa budget-ledger, has ledger-id {string(GLOBAL_LEDGER)}; '
                 f'update $l has limit-micros {limit}; $l has warning-micros {warning};').resolve()
    atomically(driver, db, work)


class Budget:
    """The shared spend ledger in TypeDB. Amounts are integers in micro-dollars.

    The limit is read from the ledger on every reservation; nothing here can raise it.
    """

    def __init__(self, driver, db):
        self._driver, self._db = driver, db
        self._ensure_ledger()

    def _ensure_ledger(self):
        """Make sure the ledger exists (with no limit, it refuses every reservation)."""
        def work(tx):
            if not tx_fetch(tx, f'match $l isa budget-ledger, has ledger-id {string(GLOBAL_LEDGER)}; '
                                f'fetch {{ "id": $l.ledger-id }};'):
                tx.query(f'insert $l isa budget-ledger, has ledger-id {string(GLOBAL_LEDGER)}, '
                         f'has committed-micros 0;').resolve()
        try:
            atomically(self._driver, self._db, work)
        except TypeDBDriverException:
            pass   # another process created it at the same moment (@key); that's fine

    def _ledger(self, tx):
        rows = tx_fetch(tx, f'match $l isa budget-ledger, has ledger-id {string(GLOBAL_LEDGER)}; '
                            f'fetch {{ "committed": $l.committed-micros, "limit": $l.limit-micros, '
                            f'"warning": $l.warning-micros }};')
        return rows[0] if rows else None

    def _set_committed(self, tx, value):
        tx.query(f'match $l isa budget-ledger, has ledger-id {string(GLOBAL_LEDGER)}; '
                 f'update $l has committed-micros {value};').resolve()

    def _atomically(self, work):
        return atomically(self._driver, self._db, work, retries=RESERVE_RETRIES)

    def reserve(self, purpose, model, max_micros, prompt_version="none", run_id=None):
        """Reserve the maximum cost of one call; returns the call id. Links the call to the
        analysis run, if given, so a run's cost can be inspected."""
        call_id = secrets.token_hex(12)

        def work(tx):
            ledger = self._ledger(tx)
            if ledger is None or ledger["limit"] is None:
                raise BudgetNotInitialised("the model budget has no limit set; set one with "
                                           "scripts/set_budget.py before any model call")
            if ledger["committed"] + max_micros > ledger["limit"]:
                raise BudgetExceeded(
                    f"this call could cost up to ${usd(max_micros):.4f}; ${usd(ledger['committed']):.4f} "
                    f"of the ${usd(ledger['limit']):.2f} budget is already committed")
            self._set_committed(tx, ledger["committed"] + max_micros)
            tx.query(f'insert $c isa model-call, has call-id {string(call_id)}, has provider '
                     f'{string(PROVIDER)}, has model-id {string(model)}, has prompt-version '
                     f'{string(prompt_version)}, has call-purpose {string(purpose)}, '
                     f'has call-status "reserved", has reserved-micros {max_micros}, '
                     f'has created-at {now()};').resolve()
            if run_id:
                rows = tx.query(f'match $c isa model-call, has call-id {string(call_id)}; '
                                f'$r isa analysis-run, has run-id {string(run_id)}; '
                                f'insert run-call (run: $r, call: $c);').resolve().as_concept_rows()
                if len(list(rows)) != 1:
                    raise LookupError(f"no analysis run {run_id!r}")
        self._atomically(work)
        return call_id

    def _call(self, tx, call_id):
        rows = tx_fetch(tx, f'match $c isa model-call, has call-id {string(call_id)}; '
                            f'fetch {{ "status": $c.call-status, "reserved": $c.reserved-micros }};')
        if not rows:
            raise LookupError(f"no model call {call_id!r}")
        return rows[0]["status"], rows[0]["reserved"]

    def settle(self, call_id, actual_micros, status="settled", input_tokens=None,
               output_tokens=None, stop_reason=None, detail=None):
        """Replace a reservation with the real cost (zero for a request the API rejected)."""
        def work(tx):
            current, reserved = self._call(tx, call_id)
            if current not in ("reserved", "held"):
                raise ValueError(f"call {call_id} is already {current}")
            self._set_committed(tx, self._ledger(tx)["committed"] - reserved + actual_micros)
            extra = "".join([f", has input-tokens {input_tokens}" if input_tokens is not None else "",
                             f", has output-tokens {output_tokens}" if output_tokens is not None else "",
                             f", has stop-reason {string(stop_reason)}" if stop_reason else ""])
            note = f" $c has call-detail {string(detail[:500])};" if detail else ""
            tx.query(f'match $c isa model-call, has call-id {string(call_id)}; '
                     f'update $c has call-status {string(status)};{note}').resolve()
            tx.query(f'match $c isa model-call, has call-id {string(call_id)}; '
                     f'insert $c has actual-micros {actual_micros}, has settled-at {now()}{extra};').resolve()
        self._atomically(work)

    def hold(self, call_id, detail):
        """Keep the full reservation: the call may have been charged."""
        def work(tx):
            self._call(tx, call_id)
            tx.query(f'match $c isa model-call, has call-id {string(call_id)}; '
                     f'update $c has call-status "held"; $c has call-detail {string(detail[:500])};').resolve()
        self._atomically(work)

    def summary(self):
        """The budget and every call, in dollars and micro-dollars."""
        with self._driver.transaction(self._db, TransactionType.READ) as tx:
            ledger = self._ledger(tx)
            calls = tx_fetch(tx, 'match $c isa model-call; fetch { "id": $c.call-id, '
                                 '"status": $c.call-status, "reserved": $c.reserved-micros, '
                                 '"actual": $c.actual-micros, "purpose": $c.call-purpose };')
        to_usd = lambda v: usd(v) if v is not None else None
        return {"limit_usd": to_usd(ledger["limit"]), "warning_usd": to_usd(ledger["warning"]),
                "committed_usd": usd(ledger["committed"]),
                "warning_reached": ledger["warning"] is not None and ledger["committed"] >= ledger["warning"],
                "held": [c for c in calls if c["status"] == "held"], "calls": calls}


API_BASE_URL = "https://api.anthropic.com"


def client_options(api_key, timeout):
    """How the real client is built. max_retries=0: the SDK must not retry on its own, outside
    the budget. base_url is fixed so the key only ever goes to Anthropic's own API, whatever
    ANTHROPIC_BASE_URL may be set to in the environment."""
    return {"api_key": api_key, "base_url": API_BASE_URL, "max_retries": 0, "timeout": timeout}


def _real_client(api_key, timeout):
    import anthropic    # imported here so tests never touch it unless asked to
    return anthropic.Anthropic(**client_options(api_key, timeout))


def _status_of(error):
    return getattr(error, "status_code", None)


def _is_connection_problem(error):
    import anthropic
    return isinstance(error, anthropic.APIConnectionError)


class ClaudeProvider:
    """Structured requests to Claude, each one inside the budget."""
    provider = PROVIDER

    def __init__(self, budget, api_key=None, pricing=None, client=None, timeout=180.0, sleep=time.sleep):
        self.budget = budget
        self.pricing = pricing or load_pricing()
        self.model = self.pricing.model
        self._client = client if client is not None else _real_client(api_key, timeout)
        self._sleep = sleep

    def structured(self, purpose, system, user_text, schema, max_tokens=MAX_OUTPUT_TOKENS,
                   prompt_version="none", run_id=None):
        if not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError(f"max_tokens must be between 1 and {MAX_OUTPUT_TOKENS}")
        # Thinking is always on for this model; effort is set explicitly (its default is medium).
        request = {"model": self.model, "max_tokens": max_tokens, "system": system,
                   "messages": [{"role": "user", "content": user_text}],
                   "output_config": {"effort": "medium",
                                     "format": {"type": "json_schema", "schema": schema}}}
        input_bytes = len(json.dumps(request).encode())
        if input_bytes > MAX_INPUT_BYTES:
            raise ValueError(f"request is {input_bytes} bytes; the limit is {MAX_INPUT_BYTES}")
        ceiling = max_cost_micros(self.pricing, input_bytes, max_tokens)
        held_any = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            call_id = self.budget.reserve(purpose, self.model, ceiling, prompt_version, run_id)  # may refuse: nothing sent
            try:
                response = self._client.messages.create(**request)
            except Exception as error:
                status = _status_of(error)
                if status is not None and status in NOT_CHARGED:
                    self.budget.settle(call_id, 0, status="failed", detail=f"HTTP {status}: rejected, not charged")
                elif status is not None or _is_connection_problem(error):
                    self.budget.hold(call_id, f"{type(error).__name__} (HTTP {status}): may have been "
                                              f"charged; reconcile against the Anthropic Console")
                    held_any = True
                else:
                    self.budget.hold(call_id, f"unexpected {type(error).__name__}; reconcile manually")
                    raise CallFailed(f"unexpected error: {type(error).__name__}", held=True) from error
                retryable = status in RETRYABLE or (status is None and _is_connection_problem(error))
                if retryable and attempt < MAX_ATTEMPTS:
                    self._sleep(min(2 ** attempt, 20))
                    continue
                raise CallFailed(f"the model request failed: {type(error).__name__} (HTTP {status})",
                                 held=held_any) from error
            usage = response.usage
            self.budget.settle(call_id, actual_cost_micros(self.pricing, usage), status="settled",
                               input_tokens=getattr(usage, "input_tokens", None),
                               output_tokens=getattr(usage, "output_tokens", None),
                               stop_reason=response.stop_reason)
            if response.stop_reason == "refusal":
                raise ModelRefused("the model declined to answer", held=held_any)
            if response.stop_reason == "max_tokens":
                raise BadOutput("the answer was cut off at the output limit", held=held_any)
            text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
            try:
                return json.loads(text)
            except (TypeError, ValueError) as error:
                raise BadOutput("the answer wasn't valid JSON", held=held_any) from error
        raise CallFailed("no attempts left", held=held_any)


class UnavailableProvider:
    """A configured provider that can't be used right now (e.g. stale prices): every request
    raises the reason, so the claims stage records it instead of calling anything."""
    provider, model = PROVIDER, MODEL

    def __init__(self, error):
        self.error = error

    def structured(self, *args, **kwargs):
        raise self.error


def provider_from_settings(settings, driver, db):
    """The configured model provider, or None when NEWSLENS_MODEL_PROVIDER is "none"."""
    if settings.newslens_model_provider == "none":
        return None
    try:
        pricing = load_pricing()
    except PricingOutOfDate as error:
        return UnavailableProvider(error)
    return ClaudeProvider(Budget(driver, db), api_key=settings.anthropic_api_key.get_secret_value(),
                          pricing=pricing)

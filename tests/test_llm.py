"""The model gateway and the hard spend cap, with a fake client. No real API calls.

Adapted from Charcoal's tests/test_llm.py (same author)."""

import json
import re
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fake_claude import FakeClaude, http_error, reply, timeout
from newslens.db import connect, now, read, write
from newslens.llm import (MAX_OUTPUT_TOKENS, BadOutput, Budget, BudgetExceeded,
                          BudgetNotInitialised, CallFailed, ClaudeProvider, ModelRefused,
                          PricingOutOfDate, actual_cost_micros, load_pricing, max_cost_micros,
                          set_budget_limit)

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
          "additionalProperties": False}
PRICING = load_pricing(today=date(2026, 10, 26))


def capped(driver, db, limit, warning=None):
    set_budget_limit(driver, db, limit, warning)
    return Budget(driver, db)


def gateway(budget, *script):
    fake = FakeClaude(*script)
    return ClaudeProvider(budget, pricing=PRICING, client=fake, sleep=lambda s: None), fake


def ask(model, run_id=None):
    return model.structured("test", "system", "user", SCHEMA, max_tokens=1000,
                            prompt_version="test-v1", run_id=run_id)


def statuses(budget):
    return [c["status"] for c in budget.summary()["calls"]]


def _request_bytes():
    return json.dumps({"model": "claude-opus-5-5", "max_tokens": 1000, "system": "system",
                       "messages": [{"role": "user", "content": "user"}],
                       "output_config": {"effort": "medium",
                                         "format": {"type": "json_schema", "schema": SCHEMA}}})


# --- pricing ------------------------------------------------------------------------------

def test_pricing_comes_from_dated_configuration():
    assert PRICING.model == "claude-opus-5-5"
    assert (PRICING.input, PRICING.output) == (Decimal("4.00"), Decimal("20.00"))
    assert PRICING.source.startswith("https://")
    with pytest.raises(PricingOutOfDate):
        load_pricing(today=date(2027, 1, 1))


def test_cost_arithmetic_in_micro_dollars():
    assert max_cost_micros(PRICING, 1000, 1000) == (1000 + 2000) * 4 + 1000 * 20
    usage = reply(input_tokens=1000, output_tokens=500).usage
    assert actual_cost_micros(PRICING, usage) == 1000 * 4 + 500 * 20      # $0.014


def test_only_llm_py_talks_to_the_model():
    package = Path(__file__).parent.parent / "newslens"
    uses_sdk = re.compile(r"^\s*(import anthropic|from anthropic)|\banthropic\.", re.MULTILINE)
    offenders = [str(p) for p in package.rglob("*.py")
                 if p.name != "llm.py" and uses_sdk.search(p.read_text())]
    assert offenders == []


def test_tests_cannot_create_a_real_client(driver, db):
    with pytest.raises(RuntimeError, match="real Claude client"):
        ClaudeProvider(Budget(driver, db), api_key="not-a-real-key", pricing=PRICING)


# --- normal calls -------------------------------------------------------------------------

def test_a_successful_call_reserves_then_settles_to_actual_cost(driver, db):
    budget = capped(driver, db, 20, 15)
    model, fake = gateway(budget, reply({"ok": True}, input_tokens=1000, output_tokens=500))
    assert ask(model) == {"ok": True}
    [call] = budget.summary()["calls"]
    assert call["status"] == "settled" and call["actual"] == 14_000 and call["reserved"] > 14_000
    assert budget.summary()["committed_usd"] == Decimal("0.014")
    request = fake.requests[0]
    assert request["model"] == "claude-opus-5-5" and request["max_tokens"] == 1000
    assert request["output_config"] == {"effort": "medium",
                                        "format": {"type": "json_schema", "schema": SCHEMA}}
    assert "fallbacks" not in request and "thinking" not in request


def test_calls_are_linked_to_their_analysis_run(driver, db):
    write(driver, db, f'insert $r isa analysis-run, has run-id "r1", has run-status "running", '
                      f'has created-at {now()};')
    model, _ = gateway(capped(driver, db, 1), reply({"ok": True}))
    ask(model, run_id="r1")
    rows = read(driver, db, 'match $r isa analysis-run, has run-id "r1"; run-call (run: $r, call: $c); '
                            '$c isa model-call; fetch { "model": $c.model-id, "prompt": $c.prompt-version };')
    assert rows == [{"model": "claude-opus-5-5", "prompt": "test-v1"}]


def test_request_bounds_are_enforced_before_reserving(driver, db):
    budget = capped(driver, db, 1)
    model, fake = gateway(budget)
    with pytest.raises(ValueError):
        model.structured("t", "s", "u", SCHEMA, max_tokens=MAX_OUTPUT_TOKENS + 1)
    with pytest.raises(ValueError):
        model.structured("t", "s", "x" * 600_000, SCHEMA, max_tokens=100)
    assert fake.requests == [] and budget.summary()["calls"] == []


# --- the cap --------------------------------------------------------------------------------

def test_no_limit_means_no_calls(driver, db):
    model, fake = gateway(Budget(driver, db), reply({"ok": True}))
    with pytest.raises(BudgetNotInitialised):
        ask(model)
    assert fake.requests == []


def test_a_call_that_could_exceed_the_cap_is_refused_before_sending(driver, db):
    budget = capped(driver, db, "0.02", "0.01")
    model, fake = gateway(budget, reply({"ok": True}))
    with pytest.raises(BudgetExceeded):
        ask(model)                                     # its maximum cost is about $0.029
    assert fake.requests == [] and budget.summary()["committed_usd"] == 0


def test_the_warning_level(driver, db):
    budget = capped(driver, db, "1", "0.01")
    model, _ = gateway(budget, reply({"ok": True}, input_tokens=1000, output_tokens=500))
    ask(model)
    assert budget.summary()["warning_reached"]


def test_concurrent_reservations_cannot_overspend(driver, db):
    budget = capped(driver, db, "0.000030", "0.00002")  # 30 micro-dollars
    results, start = [], threading.Barrier(10)
    def worker():
        own = Budget(driver, db)
        start.wait()
        try:
            own.reserve("race", "claude-opus-5-5", 10)
            results.append("ok")
        except BudgetExceeded:
            results.append("refused")
    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results.count("ok") == 3 and results.count("refused") == 7
    assert budget.summary()["committed_usd"] == Decimal("0.00003")


def test_the_budget_survives_a_restart(driver, db, settings):
    budget = capped(driver, db, "1", "0.5")
    model, _ = gateway(budget, reply({"ok": True}, input_tokens=1000, output_tokens=500))
    ask(model)
    fresh = connect(settings)                          # a new connection, as after a restart
    try:
        again = Budget(fresh, db)
        assert again.summary()["committed_usd"] == Decimal("0.014")
        with pytest.raises(BudgetExceeded):
            again.reserve("big", "claude-opus-5-5", 990_000)     # 0.014 + 0.99 > 1
    finally:
        fresh.close()


# --- failures, retries and accounting ------------------------------------------------------

def test_rejected_requests_cost_nothing_and_retries_are_bounded(driver, db):
    budget = capped(driver, db, 1)
    model, fake = gateway(budget, http_error(429), http_error(529), http_error(429))
    with pytest.raises(CallFailed) as raised:
        ask(model)
    assert len(fake.requests) == 3 and not raised.value.held
    assert statuses(budget) == ["failed"] * 3 and budget.summary()["committed_usd"] == 0


def test_a_bad_request_is_not_retried(driver, db):
    model, fake = gateway(capped(driver, db, 1), http_error(400), reply({"ok": True}))
    with pytest.raises(CallFailed):
        ask(model)
    assert len(fake.requests) == 1


def test_a_timeout_keeps_its_reservation_until_reconciled(driver, db):
    budget = capped(driver, db, 1)
    model, _ = gateway(budget, timeout(), reply({"ok": True}, input_tokens=1000, output_tokens=500))
    assert ask(model) == {"ok": True}                  # retried once, with a new reservation
    summary = budget.summary()
    (held,) = summary["held"]
    assert held["actual"] is None
    assert summary["committed_usd"] == Decimal(held["reserved"] + 14_000) / 1_000_000
    budget.settle(held["id"], 0, status="settled", detail="checked in the Console: not charged")
    assert budget.summary()["committed_usd"] == Decimal("0.014")


def test_retries_cannot_bypass_the_cap(driver, db):
    probe = max_cost_micros(PRICING, len(_request_bytes()), 1000)
    limit = Decimal(probe * 3 // 2) / 1_000_000            # one held reservation fills it
    model, fake = gateway(capped(driver, db, limit, limit), timeout(), reply({"ok": True}))
    with pytest.raises(BudgetExceeded):
        ask(model)
    assert len(fake.requests) == 1                     # the retry was refused before sending


def test_refusals_and_bad_output_are_charged_and_reported(driver, db):
    budget = capped(driver, db, 1)
    model, _ = gateway(budget, reply({"ok": True}, stop="refusal", input_tokens=100, output_tokens=10),
                       reply(text="{not json", input_tokens=100, output_tokens=10),
                       reply({"ok": True}, stop="max_tokens", input_tokens=100, output_tokens=1000))
    with pytest.raises(ModelRefused):
        ask(model)
    with pytest.raises(BadOutput):
        ask(model)
    with pytest.raises(BadOutput):
        ask(model)
    assert statuses(budget) == ["settled"] * 3
    assert budget.summary()["committed_usd"] == Decimal(3 * 400 + 200 + 200 + 20_000) / 1_000_000


def test_a_call_that_does_not_fit_the_remaining_budget_is_not_sent(driver, db):
    """Earlier spending counts: a call whose maximum cost exceeds what is LEFT is refused."""
    probe = max_cost_micros(PRICING, len(_request_bytes()), 1000)
    limit = Decimal(probe * 3 // 2) / 1_000_000            # room for one call's ceiling, not two
    budget = capped(driver, db, limit, limit)
    model, fake = gateway(budget, reply({"ok": True}, input_tokens=100, output_tokens=10),
                          reply({"ok": True}))
    ask(model)                                         # fits; settles to its small real cost
    budget.reserve("other", "claude-opus-5-5", probe // 2 + 1)   # something else uses part of what's left
    with pytest.raises(BudgetExceeded):
        ask(model)                                     # its ceiling no longer fits what remains
    assert len(fake.requests) == 1                     # the second request was never sent

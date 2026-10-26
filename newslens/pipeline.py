"""One analysis run: retrieve -> extract -> claims, each recorded as a stage in TypeDB.

Outcomes are reported honestly at every step:
- An article that could not be retrieved is marked as such (failed, not permitted, or
  paywalled) with the reason, and the run fails. Nothing is analysed from a headline alone.
- Each stage's results are saved in one transaction, after they have been checked.
- Claim extraction is skipped (with the reason) when no model provider is configured, or when
  the site does not allow its text to be sent to an AI provider.
- Model errors, budget refusals and invalid answers fail the claims stage; the article and its
  extracted text stay available.
"""

import logging
from urllib.parse import urlsplit

from newslens import store
from newslens.claims import InvalidAnswer, extract_claims
from newslens.ingest.extract import (HTML_TYPES, Article, extract_article, header_opt_out,
                                     media_type, with_text)
from newslens.ingest.robots import load_rules
from newslens.llm import BudgetExceeded, CallFailed, PricingOutOfDate

log = logging.getLogger("newslens.pipeline")


class Stop(Exception):
    """The run can't continue; the message says why, in plain words."""


def _retrieve(driver, db, run_id, target, fetcher):
    """Fetch the article page. Returns (response, ai_decision_reason or None)."""
    url = target["url"]
    store.start_stage(driver, db, run_id, "retrieve")
    rules = load_rules(fetcher, url)
    if rules.unsafe_address:
        note = (f"Not retrieved: this address leads to a network NewsLens never connects to "
                f"({rules.unsafe_address}). Only public websites can be retrieved.")
        store.save_retrieval(driver, db, target["article_id"], "failed", [note])
        store.finish_stage(driver, db, run_id, "retrieve", "failed", [note])
        raise Stop(note)
    decision = rules.may_fetch(url)
    if not decision.allowed:
        note = f"Not retrieved: {decision.reason}. You can paste the article text instead."
        store.save_retrieval(driver, db, target["article_id"], "not-permitted", [note])
        store.finish_stage(driver, db, run_id, "retrieve", "failed", [note])
        raise Stop(note)
    response = fetcher.get(url)
    if response.final_url != url:
        # The redirect target's rules apply to its content. (It was fetched before they could
        # be read, since the target wasn't known; if they refuse, the content is discarded.)
        if urlsplit(response.final_url).netloc != urlsplit(url).netloc:
            rules = load_rules(fetcher, response.final_url)
        decision = rules.may_fetch(response.final_url)
        if not decision.allowed:
            note = f"Not used: the page redirected to {response.final_url}, and {decision.reason}."
            store.save_retrieval(driver, db, target["article_id"], "not-permitted", [note], response)
            store.finish_stage(driver, db, run_id, "retrieve", "failed", [note])
            raise Stop(note)
    if response.status in (401, 403):
        status, note = "not-permitted", (f"The site refused access (HTTP {response.status}). "
                                         "NewsLens does not get around access restrictions; you can "
                                         "paste the article text instead.")
    elif response.status == 402:
        status, note = "paywalled", "The site requires payment (HTTP 402). You can paste the text instead."
    elif not response.ok:
        status, note = "failed", f"Could not retrieve the page: {response.error or f'HTTP {response.status}'}."
    elif media_type(response.content_type) not in HTML_TYPES:
        status, note = "failed", f"The address is not a web page ({media_type(response.content_type) or 'unknown type'})."
    else:
        status, note = None, None
    if status:
        store.save_retrieval(driver, db, target["article_id"], status, [note], response)
        store.finish_stage(driver, db, run_id, "retrieve", "failed", [note])
        raise Stop(note)
    details = [f"Fetched {response.final_url} (HTTP {response.status}, {len(response.body)} bytes)."]
    if response.redirects:
        details.append(f"Followed {len(response.redirects)} redirect(s).")
    ai = rules.may_send_to_ai(response.final_url)
    ai_refusal = header_opt_out(response.headers) or (None if ai.allowed else ai.reason)
    store.save_retrieval(driver, db, target["article_id"], "retrieved", [], response)
    store.finish_stage(driver, db, run_id, "retrieve", "completed", details)
    return response, ai_refusal


def _extract(driver, db, run_id, target, response):
    store.start_stage(driver, db, run_id, "extract")
    if response is None:                        # manual text
        extracted = with_text(Article(), target["text"])
        extracted.sources.append("text: entered manually")
    else:
        extracted = extract_article(response.body, response.content_type, response.final_url)
    if extracted.error:
        note = f"No article could be extracted: {extracted.error}."
        store.save_retrieval(driver, db, target["article_id"], "failed", [note])
        store.finish_stage(driver, db, run_id, "extract", "failed", [note])
        raise Stop(note)
    store.save_extraction(driver, db, target["article_id"], run_id, extracted,
                          source_url=response.final_url if response else target["url"],
                          manual=response is None)
    notes = []
    if extracted.truncated:
        notes.append("The text was longer than the limit and was cut; only the first part is analysed.")
    if extracted.paywalled:
        notes.append("The page marks itself as not free to read; the text may be only a preview.")
    if response is not None and (notes or extracted.paywalled):
        status = "paywalled" if extracted.paywalled else "partial"
        store.save_retrieval(driver, db, target["article_id"], status, notes)
    details = [f"{len(extracted.text)} characters of text, {len(extracted.quotes)} quotation(s), "
               f"{len(extracted.links)} link(s)."] + notes
    if response is None:
        details.append("Pasted text has no page markup, so no date, byline or publisher is recorded.")
    elif not extracted.published_at:
        details.append("No publication date was given in the page's markup; none is recorded.")
    store.finish_stage(driver, db, run_id, "extract", "completed", details)
    return extracted


def _claims(driver, db, run_id, target, extracted, model, ai_refusal):
    store.start_stage(driver, db, run_id, "claims")
    if model is None:
        store.finish_stage(driver, db, run_id, "claims", "skipped",
                           ["No AI model provider is configured (NEWSLENS_MODEL_PROVIDER=none), "
                            "so claims were not extracted."])
        return
    if ai_refusal:
        store.finish_stage(driver, db, run_id, "claims", "skipped",
                           [f"Claims were not extracted: {ai_refusal}."])
        return
    headline = target["title"] if target["input_method"] == "manual-text" else extracted.headline
    try:
        result = extract_claims(model, extracted.text, headline, extracted.quotes, run_id)
    except (BudgetExceeded, PricingOutOfDate) as error:
        store.finish_stage(driver, db, run_id, "claims", "failed",
                           [f"No model call was made: {error}."])
        raise Stop("claim extraction was refused by the spending limit") from None
    except (CallFailed, InvalidAnswer, ValueError) as error:
        store.finish_stage(driver, db, run_id, "claims", "failed",
                           [f"Claim extraction failed: {error}. Nothing from it was stored."])
        raise Stop("claim extraction failed") from None
    store.save_claims(driver, db, target["article_id"], run_id, result)
    details = [f"{len(result.claims)} claim(s) kept, each quoting the article exactly; "
               f"{len(result.speakers)} quotation speaker(s) identified."]
    if result.rejected:
        details.append(f"{len(result.rejected)} item(s) from the model were discarded:")
        details += result.rejected[:20]
    store.finish_stage(driver, db, run_id, "claims", "completed", details)


def run_analysis(driver, db, run_id, fetcher, model):
    """Run every stage of a claimed run and record the outcome. Never raises for expected
    problems; unexpected errors are recorded as a failed run and re-raised."""
    target = store.run_target(driver, db, run_id)
    try:
        if target["input_method"] == "manual-text":
            store.start_stage(driver, db, run_id, "retrieve")
            store.finish_stage(driver, db, run_id, "retrieve", "skipped",
                               ["The article text was entered manually; nothing was fetched."])
            response, ai_refusal = None, None
        else:
            response, ai_refusal = _retrieve(driver, db, run_id, target, fetcher)
        extracted = _extract(driver, db, run_id, target, response)
        _claims(driver, db, run_id, target, extracted, model, ai_refusal)
    except Stop as stop:
        store.finish_run(driver, db, run_id, "failed", str(stop))
        return "failed"
    except Exception as error:
        log.exception("run %s failed unexpectedly", run_id)
        store.fail_running_stages(driver, db, run_id, "Stopped by an unexpected error.")
        store.finish_run(driver, db, run_id, "failed",
                         f"An unexpected error stopped the run ({type(error).__name__}).")
        raise
    store.finish_run(driver, db, run_id, "completed")
    return "completed"

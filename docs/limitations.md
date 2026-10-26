# Known limitations (Milestone 2)

Honest gaps in what NewsLens does today. Each is a candidate for a later milestone.

## Retrieval
- Pages that build their text with JavaScript are not supported: only the HTML the server
  sends is read. Such pages usually fail with "no article text was found". Paste the text instead.
- Paywall detection relies on the page saying so (`isAccessibleForFree: false` in its markup)
  or on HTTP 401/402/403. A paywall that sends a preview without saying so is not detected.
- A robots.txt that can't be read (timeout, server error) is treated as "no permission".
- A redirect target is fetched before its site's robots.txt can be checked (its address isn't
  known in advance); if those rules refuse, the content is discarded.
- Images, captions and image descriptions are not extracted yet.

## Extraction
- Main-text extraction (trafilatura) can include or miss boilerplate such as related-article
  lists or captions; the stored text is exactly what was extracted, so positions stay correct.
- "Passages in quotation marks" are found by double quotation marks. They include titles and
  scare quotes as well as things people said. Single quotation marks (common in British
  newspapers) are not detected, because they can't be told apart from apostrophes reliably.
- Bylines are kept exactly as the page gives them; no attempt is made to identify people.
  The same name on two articles is not assumed to be the same person.
- Articles over 100,000 characters are cut at that length and marked "partial".

## Claims
- Claims are extracted by an AI model. The quote check guarantees each claim points at real
  text in the article; it does not guarantee the claim's wording represents that text fairly.
  The interface always shows the article's passage next to the model's wording.
- A claim whose quote differs from the article by even one character is discarded (the
  discard is recorded). Some genuine claims may be lost this way.
- Claims are not yet assessed against evidence: nothing is labelled true or false.
- Speaker attribution for quotations is the model's suggestion, kept only if the name appears
  in the article, and shown as a model attribution with its confidence.
- No real model run has been made yet: claim extraction has been tested with a fake model
  only. Quality on real articles is unmeasured until an approved evaluation (Milestone 7).

## Runs
- A run that is interrupted (worker crash) is marked failed and not restarted, so a model
  call is never repeated automatically; submit the article again.
- Re-analysing an existing article is not supported yet; submitting the address again
  creates a new article record.

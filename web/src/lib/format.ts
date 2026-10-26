export function formatTime(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

// Plain-English labels. Colour is never the only signal: every status has words.
export const RETRIEVAL_LABELS: Record<string, string> = {
  queued: 'Waiting to be retrieved',
  retrieved: 'Retrieved',
  partial: 'Retrieved in part',
  paywalled: 'Paywalled or preview only',
  'not-permitted': 'Not permitted to retrieve',
  failed: 'Could not be retrieved',
  manual: 'Text entered manually',
}

export const RUN_LABELS: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

export const STAGE_LABELS: Record<string, string> = {
  retrieve: 'Retrieve the page',
  extract: 'Extract text and metadata',
  claims: 'Extract claims',
}

export const KIND_LABELS: Record<string, string> = {
  factual: 'Factual',
  causal: 'Causal',
  predictive: 'Predictive',
  interpretive: 'Interpretive',
  normative: 'Normative',
  opinion: 'Opinion',
}

export const BASIS_LABELS: Record<string, string> = {
  stated: 'Stated in the article',
  implied: 'Implied by the wording',
  'model-inferred': 'Inferred by the model',
}

// A link is shown as clickable only if it is an ordinary web address.
export const isWebAddress = (url: string) => /^https?:\/\//i.test(url)

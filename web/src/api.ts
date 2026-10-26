// The only place the frontend talks to the backend. Types mirror newslens/models.py.

export type Stage = {
  name: string
  status: string
  started_at: string
  finished_at: string | null
  details: string[]
}

export type ModelCall = {
  model: string
  prompt_version: string
  status: string
  input_tokens: number | null
  output_tokens: number | null
}

export type Run = {
  id: string
  status: string
  stage: string | null
  created_at: string
  finished_at: string | null
  failure_reason: string | null
  methodology_version: string
  stages: Stage[]
  model_calls: ModelCall[]
}

export type Article = {
  id: string
  url: string | null
  title: string | null
  retrieval_status: string
  input_method: string
  created_at: string
  runs: Run[]
}

export type Quotation = {
  id: string
  start: number
  end: number
  text: string
  speakers: { name: string; confidence: string }[]
}

export type Claim = {
  id: string
  text: string
  kind: string
  basis: string
  missing_information: string[]
  quote: string
  start: number
  end: number
  run_id: string
}

export type ArticleDetail = Article & {
  subheading: string | null
  canonical_url: string | null
  final_url: string | null
  http_status: number | null
  published_at: string | null
  modified_at: string | null
  retrieved_at: string | null
  language: string | null
  text: string | null
  content_hash: string | null
  bylines: string[]
  metadata_sources: string[]
  retrieval_notes: string[]
  publishers: { name: string; domain: string }[]
  quotations: Quotation[]
  links: { url: string; anchor_text: string | null }[]
  claims: Claim[]
}

export type Health = {
  status: string
  typedb: string
  database: string
  schema_version: string | null
  model_provider: string | null
  detail: string | null
}

export class ApiError extends Error {}

// FastAPI reports problems as {"detail": "..."} or, for invalid input,
// {"detail": [{"msg": "Value error, ..."}]}. Turn either into one readable sentence.
function describe(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; type?: string; loc?: string[] }
    const field = first.loc?.at(-1)
    if (first.type === 'string_too_long') return `The ${field ?? 'value'} is too long.`
    if (first.type === 'string_too_short') return `The ${field ?? 'value'} is too short.`
    if (first.msg) return first.msg.replace(/^Value error, /, '')
  }
  return `The server answered with an error (HTTP ${status}).`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('Could not reach the NewsLens server. Is it running?')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(describe(response.status, body))
  return body as T
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

export const getHealth = () => request<Health>('/api/health')
export const listArticles = () => request<Article[]>('/api/articles')
export const getArticle = (id: string) => request<ArticleDetail>(`/api/articles/${encodeURIComponent(id)}`)
export const submitArticle = (url: string) => post<Article>('/api/articles', { url })
export const submitText = (title: string, text: string, url: string) =>
  post<Article>('/api/articles/manual', { title, text, url: url.trim() || null })

export const latestRun = (article: Article): Run | undefined => article.runs.at(-1)
export const isActive = (article: Article) =>
  ['queued', 'running'].includes(latestRun(article)?.status ?? '')

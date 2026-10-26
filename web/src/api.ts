// The only place the frontend talks to the backend. Types mirror newslens/models.py.

export type Run = {
  id: string
  status: string
  created_at: string
  methodology_version: string
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

export type Health = {
  status: string
  typedb: string
  database: string
  schema_version: string | null
  detail: string | null
}

export class ApiError extends Error {}

// FastAPI reports problems as {"detail": "..."} or, for invalid input,
// {"detail": [{"msg": "Value error, ..."}]}. Turn either into one readable sentence.
function describe(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; type?: string }
    if (first.type === 'string_too_long') return 'The address is too long.'
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

export const getHealth = () => request<Health>('/api/health')
export const listArticles = () => request<Article[]>('/api/articles')
export const submitArticle = (url: string) =>
  request<Article>('/api/articles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })

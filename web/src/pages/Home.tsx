import { useEffect, useState, type FormEvent } from 'react'

import { ApiError, getHealth, isActive, latestRun, listArticles, submitArticle, submitText,
         type Article, type Health } from '@/api'
import { StatusBadge } from '@/components/analysis/StatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { RETRIEVAL_LABELS, RUN_LABELS, formatTime } from '@/lib/format'
import { articlePath } from '@/lib/router'

const message = (error: unknown) => (error instanceof ApiError ? error.message : 'Something went wrong.')

function UrlForm({ onSaved }: { onSaved: (a: Article) => void }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onSaved(await submitArticle(url))
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="article-url">Article address (URL)</Label>
        <div className="flex gap-2">
          <Input id="article-url" type="url" inputMode="url" placeholder="https://example.org/news/story"
                 value={url} onChange={(e) => setUrl(e.target.value)}
                 aria-invalid={error ? true : undefined} aria-describedby={error ? 'url-error' : undefined} />
          <Button type="submit" disabled={busy || url.trim() === ''}>{busy ? 'Saving…' : 'Analyse'}</Button>
        </div>
        <p className="text-muted-foreground text-xs">
          NewsLens fetches the page once, respecting the site's robots.txt. It does not get around paywalls or logins.
        </p>
      </div>
      {error && (
        <Alert variant="destructive" id="url-error">
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </form>
  )
}

function TextForm({ onSaved }: { onSaved: (a: Article) => void }) {
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onSaved(await submitText(title, text, url))
    } catch (e) {
      setError(message(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={onSubmit} className="space-y-3" noValidate>
      <div className="space-y-1.5">
        <Label htmlFor="text-title">Headline</Label>
        <Input id="text-title" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="text-body">Article text</Label>
        <Textarea id="text-body" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
        <p className="text-muted-foreground text-xs">
          Paste only text you are allowed to use. It is stored exactly as entered, so quotes can be checked against it.
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="text-url">Original address (optional)</Label>
        <Input id="text-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} />
      </div>
      <Button type="submit" disabled={busy || !title.trim() || !text.trim()}>{busy ? 'Saving…' : 'Analyse text'}</Button>
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Not saved</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </form>
  )
}

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [articles, setArticles] = useState<Article[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)

  async function refresh() {
    await Promise.all([
      getHealth().then((h) => { setHealth(h); setHealthError(null) },
                       (e) => { setHealth(null); setHealthError(message(e)) }),
      listArticles().then((a) => { setArticles(a); setListError(null) }, (e) => setListError(message(e))),
    ])
  }

  useEffect(() => {
    void refresh()
  }, [])

  // While anything is queued or running, check again every few seconds.
  const waiting = articles?.some(isActive) ?? false
  useEffect(() => {
    if (!waiting) return
    const timer = window.setInterval(() => void refresh(), 3000)
    return () => window.clearInterval(timer)
  }, [waiting])

  const onSaved = (article: Article) => { window.location.hash = articlePath(article.id) }

  return (
    <main className="mx-auto max-w-4xl px-4 py-10 space-y-10">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">NewsLens</h1>
        <p className="text-muted-foreground max-w-prose">
          Development build (Milestone 2). Submit an article to retrieve it, extract its text, metadata and
          quotations, and list its claims. Claims are not yet checked against evidence.
        </p>
        {health && (
          <p className="text-sm" data-testid="health">
            Database {health.typedb} · schema {health.schema_version ?? 'unknown'} · AI model:{' '}
            {health.model_provider === 'none' ? 'not configured (claims are not extracted)' : health.model_provider}
          </p>
        )}
        {healthError && (
          <Alert variant="destructive">
            <AlertTitle>The backend is not available</AlertTitle>
            <AlertDescription>{healthError}</AlertDescription>
          </Alert>
        )}
      </header>

      <section aria-labelledby="submit-heading" className="space-y-3">
        <h2 id="submit-heading" className="text-lg font-medium">Analyse an article</h2>
        <Tabs defaultValue="url">
          <TabsList>
            <TabsTrigger value="url">From an address</TabsTrigger>
            <TabsTrigger value="text">Paste the text</TabsTrigger>
          </TabsList>
          <TabsContent value="url" className="pt-3"><UrlForm onSaved={onSaved} /></TabsContent>
          <TabsContent value="text" className="pt-3"><TextForm onSaved={onSaved} /></TabsContent>
        </Tabs>
      </section>

      <section aria-labelledby="saved-heading" className="space-y-3">
        <h2 id="saved-heading" className="text-lg font-medium">Articles</h2>
        {listError && <p className="text-destructive text-sm">{listError}</p>}
        {articles && articles.length === 0 && (
          <p className="text-muted-foreground text-sm">Nothing yet. Submit an article above.</p>
        )}
        {articles && articles.length > 0 && (
          <ul className="divide-y border-y">
            {articles.map((article) => {
              const run = latestRun(article)
              return (
                <li key={article.id}>
                  <a href={articlePath(article.id)}
                     className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3 hover:bg-muted/50 focus-visible:bg-muted/50 px-1 -mx-1 rounded-sm">
                    <span className="font-medium min-w-0 flex-1 break-words">
                      {article.title ?? article.url ?? 'Untitled'}
                    </span>
                    <StatusBadge status={article.retrieval_status}
                                 label={RETRIEVAL_LABELS[article.retrieval_status] ?? article.retrieval_status} />
                    {run && <StatusBadge status={run.status} label={`Analysis: ${RUN_LABELS[run.status] ?? run.status}`} />}
                    <span className="text-muted-foreground text-xs w-full">
                      {article.title && article.url ? `${article.url} · ` : ''}submitted {formatTime(article.created_at)}
                    </span>
                  </a>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </main>
  )
}

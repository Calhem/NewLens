// Milestone 1 interface: submit an article URL and see what the backend has stored.
// Deliberately plain: the visual design is chosen later, from three proposed directions.

import { useEffect, useState, type FormEvent } from 'react'

import { ApiError, getHealth, listArticles, submitArticle, type Article, type Health } from '@/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const message = (error: unknown) =>
  error instanceof ApiError ? error.message : 'Something went wrong.'

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [articles, setArticles] = useState<Article[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [url, setUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [saved, setSaved] = useState<Article | null>(null)

  async function refresh() {
    try {
      setHealth(await getHealth())
      setHealthError(null)
    } catch (error) {
      setHealth(null)
      setHealthError(message(error))
    }
    try {
      setArticles(await listArticles())
      setListError(null)
    } catch (error) {
      setListError(message(error))
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setSubmitError(null)
    setSaved(null)
    try {
      const article = await submitArticle(url)
      setSaved(article)
      setUrl('')
      await refresh()
    } catch (error) {
      setSubmitError(message(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-10 space-y-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">NewsLens</h1>
        <p className="text-muted-foreground">
          Development build (Milestone 1). Articles you submit are saved, but they are not yet
          retrieved or analysed.
        </p>
      </header>

      <section aria-labelledby="status-heading" className="text-sm">
        <h2 id="status-heading" className="sr-only">System status</h2>
        {health && (
          <p data-testid="health">
            Database: {health.typedb} ({health.database}, schema {health.schema_version ?? 'unknown'})
          </p>
        )}
        {healthError && (
          <Alert variant="destructive">
            <AlertTitle>The backend is not available</AlertTitle>
            <AlertDescription>{healthError}</AlertDescription>
          </Alert>
        )}
      </section>

      <section aria-labelledby="submit-heading" className="space-y-3">
        <h2 id="submit-heading" className="text-lg font-medium">Submit an article</h2>
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="article-url">Article address (URL)</Label>
            <div className="flex gap-2">
              <Input
                id="article-url"
                type="url"
                inputMode="url"
                placeholder="https://example.org/news/story"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                aria-invalid={submitError ? true : undefined}
                aria-describedby={submitError ? 'submit-error' : undefined}
                required
              />
              <Button type="submit" disabled={submitting || url.trim() === ''}>
                {submitting ? 'Saving…' : 'Submit'}
              </Button>
            </div>
          </div>
        </form>
        <div aria-live="polite">
          {submitError && (
            <Alert variant="destructive" id="submit-error">
              <AlertTitle>Not saved</AlertTitle>
              <AlertDescription>{submitError}</AlertDescription>
            </Alert>
          )}
          {saved && (
            <Alert>
              <AlertTitle>Saved</AlertTitle>
              <AlertDescription>
                Stored with retrieval status “{saved.retrieval_status}”. Retrieval and analysis
                are added in the next milestone.
              </AlertDescription>
            </Alert>
          )}
        </div>
      </section>

      <section aria-labelledby="saved-heading" className="space-y-3">
        <h2 id="saved-heading" className="text-lg font-medium">Saved articles</h2>
        {listError && <p className="text-destructive text-sm">{listError}</p>}
        {articles && articles.length === 0 && (
          <p className="text-muted-foreground text-sm">Nothing saved yet. Submit an address above.</p>
        )}
        {articles && articles.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="py-2 pr-4 font-normal">Address</th>
                <th className="py-2 pr-4 font-normal">Retrieval</th>
                <th className="py-2 pr-4 font-normal">Analysis run</th>
                <th className="py-2 font-normal">Submitted</th>
              </tr>
            </thead>
            <tbody>
              {articles.map((article) => (
                <tr key={article.id} className="border-t align-top">
                  {/* Shown as text, not a link: NewsLens hasn't checked this address yet. */}
                  <td className="py-2 pr-4 break-all">{article.url ?? '(manual text)'}</td>
                  <td className="py-2 pr-4">{article.retrieval_status}</td>
                  <td className="py-2 pr-4">{article.runs.at(-1)?.status ?? 'none'}</td>
                  <td className="py-2 whitespace-nowrap">{formatTime(article.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  )
}

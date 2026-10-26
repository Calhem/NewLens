import { useEffect, useRef, useState } from 'react'

import { ApiError, getArticle, isActive, latestRun, type ArticleDetail } from '@/api'
import { ArticleText } from '@/components/analysis/ArticleText'
import { StatusBadge } from '@/components/analysis/StatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { BASIS_LABELS, KIND_LABELS, RETRIEVAL_LABELS, RUN_LABELS, STAGE_LABELS, formatTime,
         isWebAddress } from '@/lib/format'

function Field({ label, value, source }: { label: string; value: string | null; source?: string }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="break-words">
        {value ?? <span className="text-muted-foreground">Not given</span>}
        {value && source && <span className="text-muted-foreground"> · from {source}</span>}
      </dd>
    </div>
  )
}

export default function ArticleView({ id }: { id: string }) {
  const [article, setArticle] = useState<ArticleDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const textRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let stopped = false
    let timer: number | undefined
    async function load() {
      try {
        const next = await getArticle(id)
        if (stopped) return
        setArticle(next)
        setError(null)
        if (isActive(next)) timer = window.setTimeout(load, 2000)   // follow the run as it progresses
      } catch (e) {
        if (!stopped) setError(e instanceof ApiError ? e.message : 'Something went wrong.')
      }
    }
    void load()
    return () => { stopped = true; window.clearTimeout(timer) }
  }, [id])

  function select(claimId: string) {
    setSelected(claimId)
    const mark = textRef.current?.querySelector(`mark[data-claims~="${CSS.escape(claimId)}"]`)
    mark?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  if (error) {
    return (
      <main className="mx-auto max-w-4xl px-4 py-10 space-y-4">
        <a href="#/" className="text-sm underline">← All articles</a>
        <Alert variant="destructive"><AlertTitle>Could not load the article</AlertTitle>
          <AlertDescription>{error}</AlertDescription></Alert>
      </main>
    )
  }
  if (!article) return <main className="mx-auto max-w-4xl px-4 py-10" aria-busy="true">Loading…</main>

  const run = latestRun(article)
  const source = (field: string) =>
    article.metadata_sources.find((s) => s.startsWith(`${field}:`))?.slice(field.length + 1).trim()
  const claimById = new Map(article.claims.map((c) => [c.id, c]))
  const chosen = selected ? claimById.get(selected) : undefined

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 space-y-8">
      <a href="#/" className="text-sm underline">← All articles</a>

      <header className="space-y-3">
        <h1 className="text-2xl font-semibold max-w-4xl break-words">{article.title ?? article.url ?? 'Untitled'}</h1>
        {article.subheading && <p className="text-muted-foreground max-w-prose">{article.subheading}</p>}
        <div className="flex flex-wrap gap-2">
          <StatusBadge status={article.retrieval_status}
                       label={RETRIEVAL_LABELS[article.retrieval_status] ?? article.retrieval_status} />
          {run && <StatusBadge status={run.status} label={`Analysis: ${RUN_LABELS[run.status] ?? run.status}`} />}
        </div>
        {article.retrieval_notes.map((note) => (
          <Alert key={note} variant={['failed', 'not-permitted'].includes(article.retrieval_status) ? 'destructive' : 'default'}>
            <AlertDescription>{note}</AlertDescription>
          </Alert>
        ))}
        {run?.failure_reason && article.retrieval_notes.length === 0 && (
          <Alert variant="destructive"><AlertDescription>{run.failure_reason}</AlertDescription></Alert>
        )}
      </header>

      {run && (
        <section aria-labelledby="stages-heading" className="space-y-2">
          <h2 id="stages-heading" className="text-lg font-medium">Analysis stages</h2>
          {run.stages.length === 0 && <p className="text-sm text-muted-foreground">Waiting for the worker to start.</p>}
          <ol className="space-y-2">
            {run.stages.map((stage) => (
              <li key={stage.name} className="text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{STAGE_LABELS[stage.name] ?? stage.name}</span>
                  <StatusBadge status={stage.status} />
                </div>
                {stage.details.length > 0 && (
                  <ul className="mt-1 ml-4 list-disc text-muted-foreground">
                    {stage.details.map((d) => <li key={d}>{d}</li>)}
                  </ul>
                )}
              </li>
            ))}
          </ol>
          <p className="text-xs text-muted-foreground">
            Methodology {run.methodology_version}
            {run.model_calls.map((c) => ` · model ${c.model}, prompt ${c.prompt_version} (${c.status})`)}
          </p>
        </section>
      )}

      <section aria-labelledby="meta-heading" className="space-y-2">
        <h2 id="meta-heading" className="text-lg font-medium">About this article</h2>
        <dl className="space-y-1">
          <Field label="Publisher" value={article.publishers.map((p) => `${p.name} (${p.domain})`).join(', ') || null}
                 source={source('publisher-name')} />
          <Field label="By" value={article.bylines.join(', ') || null} source={source('authors')} />
          <Field label="Published" value={formatTime(article.published_at)} source={source('published-at')} />
          <Field label="Updated" value={formatTime(article.modified_at)} source={source('modified-at')} />
          <Field label="Address" value={article.final_url ?? article.url} />
          <Field label="Retrieved" value={formatTime(article.retrieved_at)} />
        </dl>
        <p className="text-xs text-muted-foreground max-w-prose">
          Dates, bylines and the publisher name come only from the page's own machine-readable markup. Where the page
          gives none, nothing is recorded rather than guessed.
        </p>
      </section>

      {article.text && (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <section aria-labelledby="text-heading" className="space-y-2 min-w-0">
            <h2 id="text-heading" className="text-lg font-medium">Article text</h2>
            <p className="text-xs text-muted-foreground">
              <span className="italic">Italic</span>: in quotation marks. <span className="underline decoration-sky-600/60 decoration-2 underline-offset-4">Underlined</span>: a
              passage a claim rests on (select it to see the claim).
            </p>
            <div ref={textRef} className="border rounded-md p-4 max-h-[70vh] overflow-y-auto">
              <ArticleText text={article.text} claims={article.claims} quotations={article.quotations}
                           selected={selected} onSelect={select} />
            </div>
          </section>

          <section aria-labelledby="claims-heading" className="space-y-3 min-w-0">
            <h2 id="claims-heading" className="text-lg font-medium">Claims ({article.claims.length})</h2>
            <p className="text-xs text-muted-foreground">
              Extracted by an AI model and kept only if the passage it quotes appears word for word in the article.
              The claim wording is the model's; the quoted passage is the article's. Claims have not been checked
              against evidence yet.
            </p>
            {article.claims.length === 0 && (
              <p className="text-sm text-muted-foreground">No claims have been extracted. The stages above say why.</p>
            )}
            <ol className="space-y-2">
              {article.claims.map((claim, i) => (
                <li key={claim.id}>
                  <button type="button" onClick={() => select(claim.id)} aria-pressed={selected === claim.id}
                          className={`w-full text-left rounded-md border p-3 text-sm space-y-1 hover:bg-muted/50 ${selected === claim.id ? 'border-sky-600 bg-sky-50 dark:bg-sky-950' : ''}`}>
                    <span className="block font-medium">{i + 1}. {claim.text}</span>
                    <span className="block text-xs text-muted-foreground">
                      {KIND_LABELS[claim.kind] ?? claim.kind} · {BASIS_LABELS[claim.basis] ?? claim.basis} ·
                      characters {claim.start}–{claim.end}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
            {chosen && (
              <div className="rounded-md border p-3 text-sm space-y-2" aria-live="polite">
                <p className="font-medium">Selected claim</p>
                <blockquote className="border-l-2 pl-3 italic">{chosen.quote}</blockquote>
                {chosen.missing_information.length > 0 && (
                  <div>
                    <p className="text-muted-foreground">Information the article does not give:</p>
                    <ul className="list-disc ml-5">{chosen.missing_information.map((m) => <li key={m}>{m}</li>)}</ul>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}

      {article.quotations.length > 0 && (
        <section aria-labelledby="quotes-heading" className="space-y-2">
          <h2 id="quotes-heading" className="text-lg font-medium">Passages in quotation marks ({article.quotations.length})</h2>
          <p className="text-xs text-muted-foreground max-w-prose">
            Found by their quotation marks, so this can include titles and scare quotes as well as things people said.
            Speakers are suggested by the AI model and kept only if the name appears in the article.
          </p>
          <ul className="space-y-2 text-sm">
            {article.quotations.map((q) => (
              <li key={q.id}>
                <q className="italic">{q.text}</q>
                <span className="text-muted-foreground">
                  {' — '}{q.speakers.length
                    ? q.speakers.map((s) => `${s.name} (model attribution, ${s.confidence} confidence)`).join(', ')
                    : 'speaker not identified'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {article.links.length > 0 && (
        <section aria-labelledby="links-heading" className="space-y-2">
          <h2 id="links-heading" className="text-lg font-medium">Links in the article ({article.links.length})</h2>
          <ul className="space-y-1 text-sm">
            {article.links.map((link) => (
              <li key={link.url + (link.anchor_text ?? '')} className="break-all">
                {link.anchor_text && <span>{link.anchor_text}: </span>}
                {isWebAddress(link.url)
                  ? <a href={link.url} target="_blank" rel="noopener noreferrer nofollow" className="underline">{link.url}</a>
                  : <span>{link.url}</span>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}

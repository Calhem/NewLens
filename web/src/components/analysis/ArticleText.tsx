// The article's extracted text, with quotations and claim passages marked.
// Text is rendered as React text nodes only: the article is untrusted and never treated as HTML.

import { Fragment, useMemo } from 'react'

import type { Claim, Quotation } from '@/api'

type Segment = { start: number; end: number; claims: string[]; quote: boolean }

function segments(text: string, claims: Claim[], quotations: Quotation[]): Segment[] {
  const points = new Set([0, text.length])
  for (const span of [...claims, ...quotations]) {
    points.add(Math.max(0, Math.min(span.start, text.length)))
    points.add(Math.max(0, Math.min(span.end, text.length)))
  }
  const sorted = [...points].sort((a, b) => a - b)
  const result: Segment[] = []
  for (let i = 0; i < sorted.length - 1; i++) {
    const [start, end] = [sorted[i], sorted[i + 1]]
    result.push({
      start,
      end,
      claims: claims.filter((c) => c.start <= start && end <= c.end).map((c) => c.id),
      quote: quotations.some((q) => q.start <= start && end <= q.end),
    })
  }
  return result
}

export function ArticleText({
  text, claims, quotations, selected, onSelect,
}: {
  text: string
  claims: Claim[]
  quotations: Quotation[]
  selected: string | null
  onSelect: (claimId: string) => void
}) {
  const parts = useMemo(() => segments(text, claims, quotations), [text, claims, quotations])
  return (
    <div className="whitespace-pre-wrap leading-7 text-[15px]">
      {parts.map((part) => {
        const content = text.slice(part.start, part.end)
        if (part.claims.length === 0 && !part.quote) return <Fragment key={part.start}>{content}</Fragment>
        const isSelected = selected !== null && part.claims.includes(selected)
        const classes = [
          part.quote ? 'italic' : '',
          part.claims.length ? 'cursor-pointer underline decoration-2 underline-offset-4 decoration-sky-600/60' : '',
          isSelected ? 'bg-sky-200 dark:bg-sky-900 rounded-sm' : '',
        ].join(' ')
        return part.claims.length ? (
          <mark
            key={part.start}
            data-claims={part.claims.join(' ')}
            className={`text-inherit ${isSelected ? '' : 'bg-transparent'} ${classes}`}
            onClick={() => onSelect(part.claims[0])}
            title={`${part.claims.length} claim(s) rest on this passage`}
          >
            {content}
          </mark>
        ) : (
          <span key={part.start} className={classes}>{content}</span>
        )
      })}
    </div>
  )
}

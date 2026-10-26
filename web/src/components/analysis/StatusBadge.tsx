import { Badge } from '@/components/ui/badge'

type Tone = 'neutral' | 'good' | 'warn' | 'bad' | 'busy'

const TONES: Record<string, Tone> = {
  queued: 'busy', running: 'busy',
  completed: 'good', retrieved: 'good', manual: 'good',
  skipped: 'neutral', partial: 'warn', paywalled: 'warn',
  failed: 'bad', 'not-permitted': 'bad', cancelled: 'neutral',
}

const CLASSES: Record<Tone, string> = {
  neutral: 'bg-muted text-foreground',
  good: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100',
  warn: 'bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100',
  bad: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100',
  busy: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100',
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <Badge variant="outline" className={`border-transparent font-medium ${CLASSES[TONES[status] ?? 'neutral']}`}>
      {label ?? status}
    </Badge>
  )
}

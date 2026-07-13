import { cn } from '@/lib/utils'
import type { ReviewStatus, RiskLevel } from '@/lib/inspection-types'
import { RISK_META, STATUS_META } from '@/lib/mock-inspections'

const toneClasses: Record<string, string> = {
  destructive: 'border-destructive/30 bg-destructive/15 text-destructive',
  warning: 'border-warning/30 bg-warning/15 text-warning',
  info: 'border-info/30 bg-info/15 text-info',
  success: 'border-success/30 bg-success/15 text-success',
  muted: 'border-border bg-muted text-muted-foreground',
}

function Pill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-0.5 font-mono text-[11px] font-medium uppercase tracking-wide',
        toneClasses[tone],
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {children}
    </span>
  )
}

export function StatusBadge({ status }: { status: ReviewStatus }) {
  const meta = STATUS_META[status]
  return <Pill tone={meta.tone}>{meta.label}</Pill>
}

export function RiskBadge({ level }: { level: RiskLevel }) {
  const meta = RISK_META[level]
  return <Pill tone={meta.tone}>{meta.label}</Pill>
}

export function riskScoreColor(score: number) {
  if (score >= 75) return 'text-destructive'
  if (score >= 45) return 'text-warning'
  return 'text-success'
}

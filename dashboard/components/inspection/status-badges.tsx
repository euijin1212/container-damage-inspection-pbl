import { cn } from '@/lib/utils'
import type { ReportStatus, ReviewStatus, RiskLevel } from '@/lib/inspection-types'
import { REPORT_META, RISK_META, STATUS_META } from '@/lib/mock-inspections'

const toneClasses: Record<string, string> = {
  destructive: 'bg-destructive/15 text-destructive',
  warning: 'bg-warning/15 text-warning',
  info: 'bg-info/15 text-info',
  success: 'bg-success/15 text-success',
  muted: 'bg-muted text-muted-foreground',
}

function Pill({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium',
        toneClasses[tone],
      )}
    >
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

export function ReportBadge({ status }: { status: ReportStatus }) {
  const meta = REPORT_META[status]
  return <Pill tone={meta.tone}>{meta.label}</Pill>
}

export function riskScoreColor(score: number) {
  if (score >= 75) return 'text-destructive'
  if (score >= 45) return 'text-warning'
  return 'text-success'
}

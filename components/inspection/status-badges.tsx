import { cn } from '@/lib/utils'
import type { ReportStatus, ReviewStatus, RiskLevel } from '@/lib/inspection-types'
import { REPORT_META, RISK_META, STATUS_META } from '@/lib/mock-inspections'

const toneClasses: Record<string, string> = {
  destructive: 'bg-red-50 text-red-700',
  warning: 'bg-orange-50 text-orange-700',
  info: 'bg-blue-50 text-blue-700',
  success: 'bg-emerald-50 text-emerald-700',
  muted: 'bg-slate-100 text-slate-600',
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

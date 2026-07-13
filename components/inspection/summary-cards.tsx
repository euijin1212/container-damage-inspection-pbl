'use client'

import { ClipboardList, FileCheck2, ScanSearch, ShieldAlert, ShieldCheck } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { Inspection } from '@/lib/inspection-types'

interface StatCard {
  key: string
  label: string
  value: number
  hint: string
  icon: React.ElementType
  accent: string
}

export function SummaryCards({ inspections }: { inspections: Inspection[] }) {
  const total = inspections.length
  const manual = inspections.filter((i) => i.status === 'MANUAL_NEEDED').length
  const audit = inspections.filter((i) => i.status === 'AUDIT_REQUIRED').length
  const auto = inspections.filter((i) => i.status === 'AUTO_OK').length
  const reports = inspections.filter((i) => i.status === 'REPORT_CREATED').length

  const cards: StatCard[] = [
    { key: 'total', label: 'Total Inspections', value: total, hint: 'Captured today', icon: ClipboardList, accent: 'text-foreground' },
    { key: 'manual', label: 'Manual Review', value: manual, hint: 'Needs inspector', icon: ShieldAlert, accent: 'text-destructive' },
    { key: 'audit', label: 'Random Audit', value: audit, hint: 'Flagged for QA', icon: ScanSearch, accent: 'text-warning' },
    { key: 'auto', label: 'Auto Approved', value: auto, hint: 'Cleared by AI', icon: ShieldCheck, accent: 'text-success' },
    { key: 'reports', label: 'Reports Completed', value: reports, hint: 'Filed & archived', icon: FileCheck2, accent: 'text-info' },
  ]

  return (
    <section aria-label="Inspection summary" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {cards.map((c) => {
        const Icon = c.icon
        return (
          <Card key={c.key} className="gap-0 p-4">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">{c.label}</span>
              <Icon className={cn('size-4', c.accent)} aria-hidden />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className={cn('text-3xl font-semibold tabular-nums tracking-tight', c.accent)}>
                {c.value.toString().padStart(2, '0')}
              </span>
            </div>
            <span className="mt-1 text-xs text-muted-foreground">{c.hint}</span>
          </Card>
        )
      })}
    </section>
  )
}

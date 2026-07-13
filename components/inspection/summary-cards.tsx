'use client'

import { ClipboardList, FileCheck2, ScanSearch, ShieldAlert, ShieldCheck } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { Inspection, ReviewStatus } from '@/lib/inspection-types'

type FilterValue = ReviewStatus | 'ALL'

interface StatCard {
  key: string
  label: string
  value: number
  hint: string
  icon: React.ElementType
  accent: string
  filter: FilterValue
  emphasize?: boolean
}

interface SummaryCardsProps {
  inspections: Inspection[]
  activeFilter: FilterValue
  onFilter: (filter: FilterValue) => void
}

export function SummaryCards({ inspections, activeFilter, onFilter }: SummaryCardsProps) {
  const total = inspections.length
  const manual = inspections.filter((i) => i.status === 'MANUAL_NEEDED').length
  const audit = inspections.filter((i) => i.status === 'AUDIT_REQUIRED').length
  const auto = inspections.filter((i) => i.status === 'AUTO_OK').length
  const reports = inspections.filter((i) => i.status === 'REPORT_CREATED').length

  const cards: StatCard[] = [
    { key: 'total', label: '전체 검수', value: total, hint: '금일 촬영', icon: ClipboardList, accent: 'text-foreground', filter: 'ALL' },
    { key: 'manual', label: '수동 검수 필요', value: manual, hint: '검수자 필요', icon: ShieldAlert, accent: 'text-destructive', filter: 'MANUAL_NEEDED', emphasize: true },
    { key: 'audit', label: '랜덤 감사 대상', value: audit, hint: '품질 감사 대상', icon: ScanSearch, accent: 'text-warning', filter: 'AUDIT_REQUIRED' },
    { key: 'auto', label: '자동 승인', value: auto, hint: 'AI 자동 처리', icon: ShieldCheck, accent: 'text-success', filter: 'AUTO_OK' },
    { key: 'reports', label: '보고서 완료', value: reports, hint: '제출 및 보관', icon: FileCheck2, accent: 'text-info', filter: 'REPORT_CREATED' },
  ]

  return (
    <section aria-label="검수 요약" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {cards.map((c) => {
        const Icon = c.icon
        const active = activeFilter === c.filter
        return (
          <Card
            key={c.key}
            role="button"
            tabIndex={0}
            aria-pressed={active}
            onClick={() => onFilter(c.filter)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onFilter(c.filter)
              }
            }}
            className={cn(
              'cursor-pointer gap-0 p-4 outline-none transition-colors hover:border-primary/50 focus-visible:ring-2 focus-visible:ring-ring',
              c.emphasize && 'border-destructive/40 bg-destructive/[0.06]',
              active && (c.emphasize ? 'border-destructive ring-1 ring-destructive/40' : 'border-primary ring-1 ring-primary/40'),
            )}
          >
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

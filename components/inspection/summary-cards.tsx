'use client'

import { cn } from '@/lib/utils'
import type { Inspection, ReviewStatus } from '@/lib/inspection-types'
import { AnimatedStatNumber } from './animated-stat-number'

type FilterValue = ReviewStatus | 'ALL'

interface FlowItem {
  label: string
  value: number
  filter: FilterValue
  highlight?: boolean
}

interface SummaryCardsProps {
  inspections: Inspection[]
  activeFilter: FilterValue
  onFilter: (filter: FilterValue) => void
}

export function SummaryCards({ inspections, activeFilter, onFilter }: SummaryCardsProps) {
  const items: FlowItem[] = [
    { label: '게이트 유입', value: inspections.length, filter: 'ALL' },
    {
      label: '승인 완료',
      value: inspections.filter((i) => i.review_status === 'DONE' || i.review_status === 'AUTO_OK').length,
      filter: 'DONE',
    },
    {
      label: '보고서 완료',
      value: inspections.filter((i) => {
        const reportStatus = i.report?.report_status ?? i.report_status
        return reportStatus === 'GENERATED' || reportStatus === 'COMPLETED'
      }).length,
      filter: 'REPORT_CREATED',
    },
  ]

  return (
    <section aria-label="검수 흐름" className="rounded-lg bg-card px-6 py-5">
      <div className="grid gap-0 md:grid-cols-3">
        {items.map((item, index) => {
          const active = activeFilter === item.filter || (item.filter === 'ALL' && activeFilter === 'ALL')

          return (
            <button
              key={item.label}
              type="button"
              aria-pressed={active}
              onClick={() => onFilter(item.filter)}
              className={cn(
                'min-w-0 px-1 py-3 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring md:px-6',
                index > 0 && 'md:border-l md:border-border/70',
                active && 'rounded-md bg-primary/5',
              )}
            >
              <span className="block text-sm text-muted-foreground">{item.label}</span>
              <AnimatedStatNumber
                value={item.value}
                className="mt-2 block text-3xl font-bold tracking-tight text-foreground"
                accentClassName="mt-2 block text-3xl font-bold tracking-tight text-primary"
              />
            </button>
          )
        })}
      </div>
    </section>
  )
}

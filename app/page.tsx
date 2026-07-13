'use client'

import { useMemo, useRef, useState } from 'react'
import { DashboardHeader } from '@/components/inspection/dashboard-header'
import { SummaryCards } from '@/components/inspection/summary-cards'
import { InspectionTable } from '@/components/inspection/inspection-table'
import { InspectionDetail } from '@/components/inspection/inspection-detail'
import { mockInspections } from '@/lib/mock-inspections'
import type { Inspection } from '@/lib/inspection-types'

export default function Page() {
  const [inspections, setInspections] = useState<Inspection[]>(mockInspections)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  const selected = useMemo(
    () => inspections.find((i) => i.id === selectedId) ?? null,
    [inspections, selectedId],
  )

  function handleSelect(inspection: Inspection) {
    setSelectedId(inspection.id)
    setOpen(true)
  }

  function patch(id: string, changes: Partial<Inspection>) {
    setInspections((prev) => prev.map((i) => (i.id === id ? { ...i, ...changes } : i)))
  }

  function handleApprove(id: string) {
    patch(id, { status: 'DONE' })
    setOpen(false)
  }

  function handleReject(id: string) {
    patch(id, { status: 'REPORT_PENDING', reportStatus: 'NOT_STARTED' })
    setOpen(false)
  }

  function handleReinspect(id: string) {
    patch(id, { status: 'AUDIT_REQUIRED' })
    setOpen(false)
  }

  function handleGenerateReport(id: string) {
    patch(id, { status: 'REPORT_PENDING', reportStatus: 'GENERATING' })
    clearTimeout(timers.current[id])
    timers.current[id] = setTimeout(() => {
      patch(id, { status: 'REPORT_CREATED', reportStatus: 'READY' })
    }, 2200)
  }

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader />
      <main className="mx-auto max-w-[1600px] space-y-6 px-4 py-6 lg:px-6">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-balance">Damage Inspection Overview</h2>
          <p className="text-sm text-muted-foreground">
            AI-triaged container inspections for the current shift. Review high-risk captures first.
          </p>
        </div>

        <SummaryCards inspections={inspections} />

        <InspectionTable inspections={inspections} onSelect={handleSelect} />
      </main>

      <InspectionDetail
        inspection={selected}
        open={open}
        onOpenChange={setOpen}
        onApprove={handleApprove}
        onReject={handleReject}
        onReinspect={handleReinspect}
        onGenerateReport={handleGenerateReport}
      />
    </div>
  )
}

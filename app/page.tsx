'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { DashboardHeader } from '@/components/inspection/dashboard-header'
import { SummaryCards } from '@/components/inspection/summary-cards'
import { InspectionTable } from '@/components/inspection/inspection-table'
import { InspectionDetail } from '@/components/inspection/inspection-detail'
import { mockInspections } from '@/lib/mock-inspections'
import type { Inspection, ReviewStatus } from '@/lib/inspection-types'

type StatusFilter = ReviewStatus | 'ALL'

const STATUS_PRIORITY: Record<ReviewStatus, number> = {
  MANUAL_NEEDED: 0,
  AUDIT_REQUIRED: 1,
  PROCESSING: 2,
  REPORT_PENDING: 3,
  FAILED: 4,
  REPORT_CREATED: 5,
  DONE: 6,
  AUTO_OK: 7,
}

// A mock high-risk capture that "arrives" while an inspector is reviewing.
const incomingInspection: Inspection = {
  id: 'INS-4835',
  containerId: 'EITU 902551-7',
  capturedAt: '2026-07-13T08:55:00Z',
  detectedDamage: '측면 대형 함몰 및 균열',
  riskScore: 96,
  riskLevel: 'HIGH',
  status: 'MANUAL_NEEDED',
  originalImage: '/containers/container-hole.png',
  gate: 'A 게이트',
  lane: '1번 레인',
  inspector: '담당자 미지정',
  aiSummary: '측면 패널에 대형 함몰과 관통 균열이 확인되어 즉시 수동 검수가 필요합니다.',
  verdict: '수동 정밀 검수 필요',
  detections: [
    { id: 'd1', label: '대형 함몰', confidence: 0.98, severity: 'HIGH', description: '측면 패널이 크게 안쪽으로 함몰되었습니다.', box: { x: 30, y: 30, width: 42, height: 40 } },
    { id: 'd2', label: '관통 균열', confidence: 0.9, severity: 'HIGH', description: '함몰부를 따라 관통 균열이 발생했습니다.', box: { x: 45, y: 42, width: 20, height: 24 } },
  ],
  ocr: { text: 'EITU 902551-7', confidence: 0.91, matchesManifest: true },
  reportStatus: 'PENDING',
}

export default function Page() {
  const [inspections, setInspections] = useState<Inspection[]>(mockInspections)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')
  const [notification, setNotification] = useState<Inspection | null>(null)
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const notifiedRef = useRef(false)

  const selected = useMemo(
    () => inspections.find((i) => i.id === selectedId) ?? null,
    [inspections, selectedId],
  )

  const processingCount = useMemo(
    () => inspections.filter((i) => i.status === 'PROCESSING').length,
    [inspections],
  )

  // Canonical review queue: reviewable items in priority order.
  const reviewQueue = useMemo(
    () =>
      inspections
        .filter((i) => i.status !== 'PROCESSING' && i.status !== 'FAILED')
        .sort((a, b) => {
          if (STATUS_PRIORITY[a.status] !== STATUS_PRIORITY[b.status]) {
            return STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status]
          }
          if (b.riskScore !== a.riskScore) return b.riskScore - a.riskScore
          return new Date(b.capturedAt).getTime() - new Date(a.capturedAt).getTime()
        }),
    [inspections],
  )

  const queueIndex = selectedId ? reviewQueue.findIndex((i) => i.id === selectedId) + 1 : 0
  const queueTotal = reviewQueue.length

  // Trigger the mock "new high-risk arrival" notification once, shortly after a drawer opens.
  useEffect(() => {
    if (!open || notifiedRef.current) return
    notifiedRef.current = true
    const t = setTimeout(() => setNotification(incomingInspection), 4000)
    return () => clearTimeout(t)
  }, [open])

  function handleSelect(inspection: Inspection) {
    setSelectedId(inspection.id)
    setOpen(true)
  }

  function patch(id: string, changes: Partial<Inspection>) {
    setInspections((prev) => prev.map((i) => (i.id === id ? { ...i, ...changes } : i)))
  }

  function goNext(currentId: string) {
    const idx = reviewQueue.findIndex((i) => i.id === currentId)
    const next = reviewQueue[idx + 1]
    if (next) {
      setSelectedId(next.id)
      setOpen(true)
    } else {
      setOpen(false)
    }
  }

  function handleApprove(id: string) {
    patch(id, { status: 'DONE' })
    goNext(id)
  }

  function handleReject(id: string, comment: string) {
    patch(id, {
      status: 'REPORT_PENDING',
      reportStatus: 'PENDING',
      reviewerComment: comment.trim() || undefined,
    })
    goNext(id)
  }

  function handleReinspect(id: string, comment: string) {
    patch(id, {
      status: 'AUDIT_REQUIRED',
      reviewerComment: comment.trim() || undefined,
    })
    goNext(id)
  }

  function handleHoldNext(id: string) {
    goNext(id)
  }

  function handleGenerateReport(id: string) {
    patch(id, { status: 'REPORT_PENDING', reportStatus: 'GENERATING' })
    clearTimeout(timers.current[id])
    timers.current[id] = setTimeout(() => {
      patch(id, {
        status: 'REPORT_CREATED',
        reportStatus: 'CREATED',
        reportCreatedAt: new Date().toISOString(),
      })
    }, 2200)
  }

  function handleRetry(id: string) {
    patch(id, { status: 'PROCESSING', reportStatus: 'PENDING', errorMessage: undefined })
    clearTimeout(timers.current[id])
    timers.current[id] = setTimeout(() => {
      patch(id, { status: 'AUDIT_REQUIRED' })
    }, 2600)
  }

  function handleManualSwitch(id: string) {
    patch(id, { status: 'MANUAL_NEEDED', errorMessage: undefined })
  }

  function openNotification() {
    if (!notification) return
    setInspections((prev) => (prev.some((i) => i.id === notification.id) ? prev : [notification, ...prev]))
    setSelectedId(notification.id)
    setOpen(true)
    setNotification(null)
  }

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader processingCount={processingCount} />
      <main className="mx-auto max-w-[1600px] space-y-8 px-6 py-10 lg:px-8">
        <div className="space-y-3">
          <h2 className="text-3xl font-bold tracking-tight text-balance">컨테이너 검수 현황</h2>
          <p className="max-w-2xl text-base text-muted-foreground">
            AI가 선별한 컨테이너 검수 건을 확인하고 필요한 조치를 진행하세요.
          </p>
        </div>

        <SummaryCards inspections={inspections} activeFilter={statusFilter} onFilter={setStatusFilter} />

        <InspectionTable
          inspections={inspections}
          selectedId={selectedId}
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
          onSelect={handleSelect}
          onRetry={handleRetry}
          onManualSwitch={handleManualSwitch}
        />
      </main>

      <InspectionDetail
        inspection={selected}
        open={open}
        onOpenChange={setOpen}
        queueIndex={queueIndex > 0 ? queueIndex : 1}
        queueTotal={queueTotal || 1}
        onApprove={handleApprove}
        onReject={handleReject}
        onReinspect={handleReinspect}
        onGenerateReport={handleGenerateReport}
        onHoldNext={() => selectedId && handleHoldNext(selectedId)}
      />

      {/* Mock new high-risk arrival notification */}
      {notification && (
        <div className="fixed bottom-4 right-4 z-50 w-[calc(100%-2rem)] max-w-sm">
          <div className="flex items-start gap-3 rounded-lg bg-card p-4 shadow-sm ring-1 ring-border/70">
            <button type="button" onClick={openNotification} className="min-w-0 flex-1 text-left">
              <p className="text-sm font-medium text-foreground">새로운 고위험 검수 건이 도착했습니다.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                {notification.containerId} · 위험 점수 {notification.riskScore}
              </p>
            </button>
            <button
              type="button"
              onClick={() => setNotification(null)}
              aria-label="알림 닫기"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

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

const POLLING_INTERVAL_MS = 3000

const STATUS_PRIORITY: Record<ReviewStatus, number> = {
  MANUAL_NEEDED: 0,
  AUDIT_REQUIRED: 1,
  PENDING_CLOUD_ANALYSIS: 2,
  REPORT_PENDING: 3,
  INFERENCE_FAILED: 4,
  REPORT_CREATED: 5,
  DONE: 6,
  AUTO_OK: 7,
}

function isInspection(value: unknown): value is Inspection {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<Inspection>
  return typeof item.event_id === 'string' && typeof item.container_id === 'string'
}

function extractInspectionItems(payload: unknown): Inspection[] {
  if (Array.isArray(payload)) return payload.filter(isInspection)
  if (!payload || typeof payload !== 'object') return []

  const body = payload as { items?: unknown; inspections?: unknown; data?: unknown }
  if (Array.isArray(body.items)) return body.items.filter(isInspection)
  if (Array.isArray(body.inspections)) return body.inspections.filter(isInspection)
  if (Array.isArray(body.data)) return body.data.filter(isInspection)
  return []
}

function mergeInspections(current: Inspection[], incoming: Inspection[]) {
  const byId = new Map(current.map((inspection) => [inspection.event_id, inspection]))

  for (const inspection of incoming) {
    byId.set(inspection.event_id, {
      ...byId.get(inspection.event_id),
      ...inspection,
    })
  }

  return Array.from(byId.values())
}

// A mock high-risk capture that "arrives" while an inspector is reviewing.
const incomingInspection: Inspection = {
  event_id: 'INS-4835',
  container_id: 'EITU 902551-7',
  captured_at: '2026-07-13T08:55:00Z',
  damage_summary: '측면 대형 함몰 및 균열',
  risk_score: 96,
  risk_level: 'HIGH',
  review_status: 'MANUAL_NEEDED',
  raw_image_url: '/containers/container-hole.png',
  assigned_inspector: '미배정',
  ai_summary: '측면 패널에 대형 함몰과 관통 균열이 확인되어 즉시 수동 검수가 필요합니다.',
  verdict: '수동 정밀 검수 필요',
  detections: [
    { id: 'd1', label: '대형 함몰', confidence: 0.98, severity: 'HIGH', description: '측면 패널이 크게 안쪽으로 함몰되었습니다.', box: { x: 30, y: 30, width: 42, height: 40 } },
    { id: 'd2', label: '관통 균열', confidence: 0.9, severity: 'HIGH', description: '함몰부를 따라 관통 균열이 발생했습니다.', box: { x: 45, y: 42, width: 20, height: 24 } },
  ],
  ocr: { text: 'EITU 902551-7', confidence: 0.91, matches_manifest: true },
  report_status: 'PENDING',
}

export default function Page() {
  const [inspections, setInspections] = useState<Inspection[]>(mockInspections)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL')
  const [notification, setNotification] = useState<Inspection | null>(null)
  const [recentlyAddedIds, setRecentlyAddedIds] = useState<Set<string>>(() => new Set())
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const knownIdsRef = useRef(new Set(mockInspections.map((inspection) => inspection.event_id)))
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const notifiedRef = useRef(false)

  const selected = useMemo(
    () => inspections.find((i) => i.event_id === selectedId) ?? null,
    [inspections, selectedId],
  )

  const processingCount = useMemo(
    () => inspections.filter((i) => i.review_status === 'PENDING_CLOUD_ANALYSIS').length,
    [inspections],
  )

  // Canonical review queue: reviewable items in priority order.
  const reviewQueue = useMemo(
    () =>
      inspections
        .filter((i) => i.review_status !== 'PENDING_CLOUD_ANALYSIS' && i.review_status !== 'INFERENCE_FAILED')
        .sort((a, b) => {
          if (STATUS_PRIORITY[a.review_status] !== STATUS_PRIORITY[b.review_status]) {
            return STATUS_PRIORITY[a.review_status] - STATUS_PRIORITY[b.review_status]
          }
          if (b.risk_score !== a.risk_score) return b.risk_score - a.risk_score
          return new Date(b.captured_at).getTime() - new Date(a.captured_at).getTime()
        }),
    [inspections],
  )

  const queueIndex = selectedId ? reviewQueue.findIndex((i) => i.event_id === selectedId) + 1 : 0
  const queueTotal = reviewQueue.length

  useEffect(() => {
    knownIdsRef.current = new Set(inspections.map((inspection) => inspection.event_id))
  }, [inspections])

  useEffect(() => {
    let active = true

    async function pollManualNeededInspections() {
      try {
        const response = await fetch('/inspections?status=MANUAL_NEEDED', { cache: 'no-store' })
        if (!response.ok) return

        const payload: unknown = await response.json()
        const incoming = extractInspectionItems(payload)
        if (!active || incoming.length === 0) return

        const newIds = incoming
          .map((inspection) => inspection.event_id)
          .filter((id) => !knownIdsRef.current.has(id))

        if (newIds.length > 0) {
          setRecentlyAddedIds(new Set(newIds))
          if (highlightTimer.current) clearTimeout(highlightTimer.current)
          highlightTimer.current = setTimeout(() => setRecentlyAddedIds(new Set()), 1800)
        }

        setInspections((prev) => mergeInspections(prev, incoming))
      } catch {
        // API가 아직 연결되지 않은 개발/시연 환경에서는 mock data를 유지합니다.
      }
    }

    pollManualNeededInspections()
    const id = setInterval(pollManualNeededInspections, POLLING_INTERVAL_MS)

    return () => {
      active = false
      clearInterval(id)
      if (highlightTimer.current) clearTimeout(highlightTimer.current)
    }
  }, [])

  // Trigger the mock "new high-risk arrival" notification once, shortly after a drawer opens.
  useEffect(() => {
    if (!open || notifiedRef.current) return
    notifiedRef.current = true
    const t = setTimeout(() => setNotification(incomingInspection), 4000)
    return () => clearTimeout(t)
  }, [open])

  function handleSelect(inspection: Inspection) {
    setSelectedId(inspection.event_id)
    setOpen(true)
  }

  function patch(id: string, changes: Partial<Inspection>) {
    setInspections((prev) => prev.map((i) => (i.event_id === id ? { ...i, ...changes } : i)))
  }

  function goNext(currentId: string) {
    const idx = reviewQueue.findIndex((i) => i.event_id === currentId)
    const next = reviewQueue[idx + 1]
    if (next) {
      setSelectedId(next.event_id)
      setOpen(true)
    } else {
      setOpen(false)
    }
  }

  function handleApprove(id: string) {
    patch(id, { review_status: 'DONE' })
    goNext(id)
  }

  function handleReject(id: string, comment: string) {
    patch(id, {
      review_status: 'REPORT_PENDING',
      report_status: 'PENDING',
      reviewer_comment: comment.trim() || undefined,
    })
    goNext(id)
  }

  function handleReinspect(id: string, comment: string) {
    patch(id, {
      review_status: 'AUDIT_REQUIRED',
      reviewer_comment: comment.trim() || undefined,
    })
    goNext(id)
  }

  function handleHoldNext(id: string) {
    goNext(id)
  }

  function handleGenerateReport(id: string) {
    patch(id, { review_status: 'REPORT_PENDING', report_status: 'GENERATING' })
    clearTimeout(timers.current[id])
    timers.current[id] = setTimeout(() => {
      patch(id, {
        review_status: 'REPORT_CREATED',
        report_status: 'GENERATED',
        report_created_at: new Date().toISOString(),
      })
    }, 2200)
  }

  function handleRetry(id: string) {
    patch(id, { review_status: 'PENDING_CLOUD_ANALYSIS', report_status: 'PENDING', error_message: undefined })
    clearTimeout(timers.current[id])
    timers.current[id] = setTimeout(() => {
      patch(id, { review_status: 'AUDIT_REQUIRED' })
    }, 2600)
  }

  function handleManualSwitch(id: string) {
    patch(id, { review_status: 'MANUAL_NEEDED', error_message: undefined })
  }

  function openNotification() {
    if (!notification) return
    setInspections((prev) => (prev.some((i) => i.event_id === notification.event_id) ? prev : [notification, ...prev]))
    setSelectedId(notification.event_id)
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
          recentlyAddedIds={recentlyAddedIds}
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
                {notification.container_id} · 위험 점수 {notification.risk_score}
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

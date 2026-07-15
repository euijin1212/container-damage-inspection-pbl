'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { DashboardHeader } from '@/components/inspection/dashboard-header'
import { SummaryCards } from '@/components/inspection/summary-cards'
import { InspectionTable } from '@/components/inspection/inspection-table'
import { InspectionDetail } from '@/components/inspection/inspection-detail'
import { getInspection, listInspections, reviewInspection } from '@/lib/api'
import type { Inspection, ReviewStatus } from '@/lib/inspection-types'
import type { StatusFilter } from '@/lib/status-filters'

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

function mergeInspections(current: Inspection[], incoming: Inspection[]) {
  const byId = new Map(current.map((inspection) => [inspection.event_id, inspection]))

  for (const inspection of incoming) {
    const prev = byId.get(inspection.event_id)
    byId.set(inspection.event_id, {
      ...prev,
      ...inspection,
      // 폴링 목록에 이미지 없으면 기존 Presigned URL 유지
      raw_image_url:
        inspection.raw_image_url && inspection.raw_image_url !== '/placeholder.svg'
          ? inspection.raw_image_url
          : prev?.raw_image_url || inspection.raw_image_url,
      detections:
        inspection.detections?.length > 0
          ? inspection.detections
          : prev?.detections || inspection.detections,
      report_url: inspection.report_url || prev?.report_url,
      report: inspection.report?.report_url
        ? inspection.report
        : inspection.report
          ? { ...prev?.report, ...inspection.report, report_url: inspection.report.report_url || prev?.report?.report_url }
          : prev?.report,
    })
  }

  return Array.from(byId.values())
}

export default function Page() {
  const [inspections, setInspections] = useState<Inspection[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('GATE_INFLOW')
  const [notification, setNotification] = useState<Inspection | null>(null)
  const [recentlyAddedIds, setRecentlyAddedIds] = useState<Set<string>>(() => new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const knownIdsRef = useRef<Set<string>>(new Set())
  const highlightTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inspectionsRef = useRef<Inspection[]>([])
  inspectionsRef.current = inspections

  const selected = useMemo(
    () => inspections.find((i) => i.event_id === selectedId) ?? null,
    [inspections, selectedId],
  )

  const processingCount = useMemo(
    () => inspections.filter((i) => i.review_status === 'PENDING_CLOUD_ANALYSIS').length,
    [inspections],
  )

  const reviewQueue = useMemo(
    () =>
      inspections
        .filter(
          (i) =>
            i.review_status !== 'PENDING_CLOUD_ANALYSIS' &&
            i.review_status !== 'INFERENCE_FAILED',
        )
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

  const refreshList = useCallback(async (opts?: { silent?: boolean }) => {
    const silent = Boolean(opts?.silent)
    try {
      if (!silent) setError(null)
      const incoming = await listInspections({
        keepImagesFrom: silent ? inspectionsRef.current : undefined,
      })

      const newIds = incoming
        .map((i) => i.event_id)
        .filter((id) => !knownIdsRef.current.has(id))

      if (knownIdsRef.current.size > 0 && newIds.length > 0) {
        setRecentlyAddedIds(new Set(newIds))
        if (highlightTimer.current) clearTimeout(highlightTimer.current)
        highlightTimer.current = setTimeout(() => setRecentlyAddedIds(new Set()), 1800)

        const high = incoming.find(
          (i) =>
            newIds.includes(i.event_id) &&
            i.review_status === 'MANUAL_NEEDED' &&
            i.risk_level === 'HIGH',
        )
        if (high) setNotification(high)
      }

      knownIdsRef.current = new Set(incoming.map((i) => i.event_id))
      setInspections((prev) => mergeInspections(prev, incoming))
      return incoming
    } catch (e) {
      if (!silent) setError(e instanceof Error ? e.message : String(e))
      throw e
    }
  }, [])

  useEffect(() => {
    let active = true

    ;(async () => {
      try {
        setLoading(true)
        await refreshList()
      } catch {
        // error banner
      } finally {
        if (active) setLoading(false)
      }
    })()

    const id = setInterval(() => {
      if (document.hidden) return
      void refreshList({ silent: true }).catch(() => {})
    }, POLLING_INTERVAL_MS)

    return () => {
      active = false
      clearInterval(id)
      if (highlightTimer.current) clearTimeout(highlightTimer.current)
    }
  }, [refreshList])

  // 분석 중(PENDING)이면 상세를 주기적으로 갱신 (S3→analyzer 결과 반영)
  useEffect(() => {
    if (!selectedId || !open) return
    const current = inspectionsRef.current.find((i) => i.event_id === selectedId)
    if (current?.review_status !== 'PENDING_CLOUD_ANALYSIS') return

    const id = setInterval(() => {
      if (document.hidden) return
      void getInspection(selectedId)
        .then((detail) => {
          setInspections((prev) => mergeInspections(prev, [detail]))
        })
        .catch(() => {})
    }, POLLING_INTERVAL_MS)

    return () => clearInterval(id)
  }, [selectedId, open, selected?.review_status])

  async function handleSelect(inspection: Inspection) {
    setSelectedId(inspection.event_id)
    setOpen(true)
    try {
      const detail = await getInspection(inspection.event_id)
      setInspections((prev) => mergeInspections(prev, [detail]))
    } catch (e) {
      console.warn('[getInspection]', e)
    }
  }

  function patch(id: string, changes: Partial<Inspection>) {
    setInspections((prev) =>
      prev.map((i) => (i.event_id === id ? { ...i, ...changes } : i)),
    )
  }

  function goNext(currentId: string) {
    const idx = reviewQueue.findIndex((i) => i.event_id === currentId)
    const next = reviewQueue[idx + 1]
    if (next) {
      setSelectedId(next.event_id)
      setOpen(true)
      void getInspection(next.event_id).then((detail) => {
        setInspections((prev) => mergeInspections(prev, [detail]))
      })
    } else {
      setOpen(false)
    }
  }

  async function handleApprove(id: string) {
    try {
      const updated = await reviewInspection(id, {
        action: 'approve',
        reviewer: 'dashboard',
        memo: '승인',
      })
      // review_status=DONE → DynamoDB Streams → report_generator
      patch(id, {
        ...(updated || {}),
        review_status: 'DONE',
        report_status: 'GENERATING',
      })
      goNext(id)
      await refreshList({ silent: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleReject(id: string) {
    try {
      await reviewInspection(id, {
        action: 'reject',
        reviewer: 'dashboard',
        memo: '반려',
      })
      // DynamoDB/S3 삭제 완료 → 목록에서 제거 후 다음 건으로
      const idx = reviewQueue.findIndex((i) => i.event_id === id)
      const next = reviewQueue[idx + 1]
      setInspections((prev) => prev.filter((i) => i.event_id !== id))
      knownIdsRef.current.delete(id)
      if (next) {
        setSelectedId(next.event_id)
        setOpen(true)
        void getInspection(next.event_id).then((detail) => {
          setInspections((prev) => mergeInspections(prev, [detail]))
        })
      } else {
        setOpen(false)
        setSelectedId(null)
      }
      await refreshList({ silent: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleReinspect(id: string, comment: string) {
    try {
      const note = comment.trim()
      const updated = await reviewInspection(id, {
        action: 'reinspect',
        reviewer: 'dashboard',
        memo: note,
      })
      // 동기 재분석 완료 → MANUAL_NEEDED 로 반영
      patch(id, {
        ...(updated || {}),
        reviewer_comment: note || undefined,
      })
      await refreshList({ silent: true })
      if (updated?.event_id) {
        void getInspection(updated.event_id).then((detail) => {
          setInspections((prev) => mergeInspections(prev, [detail]))
        })
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      // API Gateway 타임아웃 후에도 Lambda 가 갱신했을 수 있어 상세 재조회
      try {
        const detail = await getInspection(id)
        setInspections((prev) => mergeInspections(prev, [detail]))
        await refreshList({ silent: true })
      } catch {
        /* ignore */
      }
      throw e
    }
  }

  async function handleGenerateReport(id: string) {
    try {
      // 승인(DONE) 갱신으로 Streams → report_generator 재트리거
      const updated = await reviewInspection(id, {
        action: 'approve',
        reviewer: 'dashboard',
        memo: '보고서 생성',
      })
      patch(id, {
        ...(updated || {}),
        review_status: 'DONE',
        report_status: 'GENERATING',
      })
      await refreshList({ silent: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  async function handleRetry(id: string) {
    try {
      const detail = await getInspection(id)
      setInspections((prev) => mergeInspections(prev, [detail]))
      await refreshList({ silent: true })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  function handleManualSwitch(id: string) {
    patch(id, { review_status: 'MANUAL_NEEDED', error_message: undefined })
  }

  function openNotification() {
    if (!notification) return
    setSelectedId(notification.event_id)
    setOpen(true)
    void getInspection(notification.event_id).then((detail) => {
      setInspections((prev) => mergeInspections(prev, [detail]))
    })
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
            새 분석 결과는 약 {POLLING_INTERVAL_MS / 1000}초마다 자동 반영됩니다.
          </p>
          {loading && (
            <p className="text-sm text-muted-foreground">API에서 검수 목록을 불러오는 중…</p>
          )}
          {error && (
            <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              API 오류: {error}
            </p>
          )}
          {!loading && !error && inspections.length === 0 && (
            <p className="text-sm text-muted-foreground">
              표시할 검수 건이 없습니다. DynamoDB item 생성 후 S3에 이미지를 올리면 자동으로 나타납니다.
            </p>
          )}
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
        onRefreshDetail={(detail) => {
          setInspections((prev) => mergeInspections(prev, [detail]))
        }}
      />

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

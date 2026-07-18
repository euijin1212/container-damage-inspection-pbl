import type { Inspection, ReviewStatus } from '@/lib/inspection-types'

/** 요약 카드 + 테이블 공통 상태 필터 */
export type StatusFilter = 'ALL' | 'GATE_INFLOW' | 'DONE' | 'REPORT_CREATED'

export function getReportStatus(inspection: Inspection) {
  return inspection.report?.report_status ?? inspection.report_status
}

/** 게이트 유입: 분석 중 + 수동 검수 대기 + 처리 실패(재시도 가능) */
export function isGateInflow(inspection: Inspection) {
  return (
    inspection.review_status === 'PENDING_CLOUD_ANALYSIS' ||
    inspection.review_status === 'MANUAL_NEEDED' ||
    inspection.review_status === 'INFERENCE_FAILED'
  )
}

/** 보고서 작성 완료 */
export function isReportCreated(inspection: Inspection) {
  const rs = getReportStatus(inspection)
  return rs === 'GENERATED' || rs === 'COMPLETED' || String(rs) === 'CREATED'
}

/** 승인 완료 (보고서 작성 완료 건은 제외 → 보고서 완료 화면에만) */
export function isApproved(inspection: Inspection) {
  if (isReportCreated(inspection)) return false
  return inspection.review_status === 'DONE' || inspection.review_status === 'AUTO_OK'
}

/** 테이블/배지용 표시 상태 */
export function getDisplayStatus(inspection: Inspection): {
  label: string
  tone: 'destructive' | 'warning' | 'info' | 'success' | 'muted'
} {
  if (isReportCreated(inspection)) {
    return { label: '보고서 작성 완료', tone: 'success' }
  }
  const rs = getReportStatus(inspection)
  if (rs === 'GENERATING') {
    return { label: '보고서 생성 중', tone: 'info' }
  }
  const meta: Record<
    string,
    { label: string; tone: 'destructive' | 'warning' | 'info' | 'success' | 'muted' }
  > = {
    PENDING_CLOUD_ANALYSIS: { label: '분석 중', tone: 'info' },
    MANUAL_NEEDED: { label: '수동 검수 필요', tone: 'destructive' },
    AUDIT_REQUIRED: { label: '랜덤 감사 대상', tone: 'warning' },
    AUTO_OK: { label: '자동 승인', tone: 'success' },
    DONE: { label: '승인 완료', tone: 'muted' },
    REPORT_PENDING: { label: '보고서 생성 대기', tone: 'info' },
    REPORT_CREATED: { label: '보고서 작성 완료', tone: 'success' },
    INFERENCE_FAILED: { label: '처리 실패', tone: 'destructive' },
  }
  return meta[inspection.review_status] || { label: inspection.review_status, tone: 'muted' }
}

export function matchesStatusFilter(inspection: Inspection, statusFilter: StatusFilter) {
  if (statusFilter === 'ALL') return true
  if (statusFilter === 'GATE_INFLOW') return isGateInflow(inspection)
  if (statusFilter === 'REPORT_CREATED') return isReportCreated(inspection)
  if (statusFilter === 'DONE') return isApproved(inspection)
  // 보고서 작성 완료 건은 REPORT_CREATED 필터 외에서는 숨김
  if (isReportCreated(inspection)) {
    return false
  }
  return false
}

export const FILTER_LABEL: Record<StatusFilter, string> = {
  ALL: '전체',
  GATE_INFLOW: '게이트 유입',
  DONE: '승인 완료',
  REPORT_CREATED: '보고서 작성 완료',
}

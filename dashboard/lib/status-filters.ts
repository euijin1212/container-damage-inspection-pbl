import type { Inspection, ReviewStatus } from '@/lib/inspection-types'

/** 요약 카드 + 테이블 공통 상태 필터 */
export type StatusFilter = ReviewStatus | 'ALL' | 'GATE_INFLOW'

export function getReportStatus(inspection: Inspection) {
  return inspection.report?.report_status ?? inspection.report_status
}

/** 게이트 유입: 분석 중 + 승인(수동 검수) 대기 */
export function isGateInflow(inspection: Inspection) {
  return (
    inspection.review_status === 'PENDING_CLOUD_ANALYSIS' ||
    inspection.review_status === 'MANUAL_NEEDED'
  )
}

/** 승인 완료 */
export function isApproved(inspection: Inspection) {
  return inspection.review_status === 'DONE' || inspection.review_status === 'AUTO_OK'
}

/** 보고서 생성 완료 */
export function isReportCreated(inspection: Inspection) {
  const rs = getReportStatus(inspection)
  return rs === 'GENERATED' || rs === 'COMPLETED'
}

export function matchesStatusFilter(inspection: Inspection, statusFilter: StatusFilter) {
  if (statusFilter === 'ALL') return true
  if (statusFilter === 'GATE_INFLOW') return isGateInflow(inspection)
  if (statusFilter === 'REPORT_CREATED') return isReportCreated(inspection)
  if (statusFilter === 'REPORT_PENDING') {
    const rs = getReportStatus(inspection)
    return rs === 'GENERATING' || inspection.review_status === 'REPORT_PENDING'
  }
  if (statusFilter === 'DONE') return isApproved(inspection)
  return inspection.review_status === statusFilter
}

export const FILTER_LABEL: Record<StatusFilter, string> = {
  ALL: '전체',
  GATE_INFLOW: '게이트 유입',
  PENDING_CLOUD_ANALYSIS: '분석 중',
  MANUAL_NEEDED: '수동 검수 필요',
  AUDIT_REQUIRED: '랜덤 감사 대상',
  AUTO_OK: '자동 승인',
  DONE: '승인 완료',
  REPORT_PENDING: '보고서 생성 대기',
  REPORT_CREATED: '보고서 생성 완료',
  INFERENCE_FAILED: '처리 실패',
}

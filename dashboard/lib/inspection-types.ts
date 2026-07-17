export type ReviewStatus =
  | 'PENDING_CLOUD_ANALYSIS'
  | 'MANUAL_NEEDED'
  | 'AUDIT_REQUIRED'
  | 'AUTO_OK'
  | 'DONE'
  | 'REPORT_PENDING'
  | 'REPORT_CREATED'
  | 'INFERENCE_FAILED'

export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW'

export type ReportStatus = 'PENDING' | 'GENERATING' | 'GENERATED' | 'COMPLETED' | 'FAILED'

export interface BoundingBox {
  /** All values are percentages (0-100) relative to the image dimensions. */
  x: number
  y: number
  width: number
  height: number
}

export interface Detection {
  id: string
  label: string
  /** @deprecated 대시보드 미표시. 위험도 계산용으로만 내부 사용 가능 */
  confidence?: number // 0-1
  severity: RiskLevel
  description: string
  location?: string
  box: BoundingBox
}

export interface InspectionReport {
  report_status: ReportStatus
  report_created_at?: string // ISO timestamp
  /** S3 Presigned URL (PDF) */
  report_url?: string
  report_path?: string
  report_summary?: string
}

export interface Inspection {
  event_id: string
  container_id: string
  captured_at: string // ISO timestamp
  raw_image_url: string
  annotated_s3_url?: string
  image_s3_url?: string
  risk_score: number // 0-100
  risk_level: RiskLevel
  review_status: ReviewStatus
  damage_summary: string
  damage_class?: string
  severity?: RiskLevel
  location?: string
  detections: Detection[]
  ocr: {
    text: string
    confidence: number // 0-1
    matches_manifest: boolean
  }
  report_status?: ReportStatus
  report_created_at?: string // ISO timestamp
  /** S3 Presigned URL — 보고서 PDF */
  report_url?: string
  report?: InspectionReport
  assigned_inspector?: string
  reviewer_comment?: string
  ai_summary: string
  verdict: string
  error_message?: string
}

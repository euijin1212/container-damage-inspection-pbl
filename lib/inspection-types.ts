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
  confidence: number // 0-1
  severity: RiskLevel
  description: string
  box: BoundingBox
}

export interface InspectionReport {
  report_status: ReportStatus
  report_created_at?: string // ISO timestamp
}

export interface Inspection {
  event_id: string
  container_id: string
  captured_at: string // ISO timestamp
  raw_image_url: string
  annotated_s3_url?: string
  image_s3_url?: string
  edge_confidence?: number // 0-1
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
  report?: InspectionReport
  assigned_inspector?: string
  reviewer_comment?: string
  ai_summary: string
  verdict: string
  error_message?: string
}

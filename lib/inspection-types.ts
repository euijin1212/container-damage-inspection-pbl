export type ReviewStatus =
  | 'PROCESSING'
  | 'MANUAL_NEEDED'
  | 'AUDIT_REQUIRED'
  | 'AUTO_OK'
  | 'DONE'
  | 'REPORT_PENDING'
  | 'REPORT_CREATED'
  | 'FAILED'

export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW'

export type ReportStatus = 'PENDING' | 'GENERATING' | 'CREATED' | 'FAILED'

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

export interface Inspection {
  id: string
  containerId: string
  capturedAt: string // ISO timestamp
  detectedDamage: string
  riskScore: number // 0-100
  riskLevel: RiskLevel
  status: ReviewStatus
  originalImage: string
  detections: Detection[]
  ocr: {
    text: string
    confidence: number // 0-1
    matchesManifest: boolean
  }
  reportStatus: ReportStatus
  reportCreatedAt?: string // ISO timestamp
  gate: string
  lane: string
  inspector: string
  reviewerComment?: string
  aiSummary: string
  verdict: string
  errorMessage?: string
}

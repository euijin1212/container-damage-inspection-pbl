export type ReviewStatus =
  | 'MANUAL_NEEDED'
  | 'AUDIT_REQUIRED'
  | 'AUTO_OK'
  | 'DONE'
  | 'REPORT_PENDING'
  | 'REPORT_CREATED'

export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW'

export type ReportStatus = 'NOT_STARTED' | 'GENERATING' | 'READY'

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
  lane: string
  inspector: string
}

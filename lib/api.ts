import type {
  Detection,
  Inspection,
  ReportStatus,
  ReviewStatus,
  RiskLevel,
} from './inspection-types'

const BASE = (process.env.NEXT_PUBLIC_API_BASE || '').replace(/\/$/, '')

/** DynamoDB review_status — 목록 쿼리용 */
const LIST_STATUSES = [
  'MANUAL_NEEDED',
  'PENDING_CLOUD_ANALYSIS',
  'AUTO_OK',
  'DONE',
  'INFERENCE_FAILED',
  'REJECTED',
] as const

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  if (!BASE) {
    throw new Error('NEXT_PUBLIC_API_BASE 미설정 (.env.local)')
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

function asRiskLevel(v: unknown): RiskLevel {
  const s = String(v || 'MEDIUM').toUpperCase()
  if (s === 'HIGH' || s === 'MEDIUM' || s === 'LOW') return s
  return 'MEDIUM'
}

function asReviewStatus(v: unknown): ReviewStatus {
  const s = String(v || 'MANUAL_NEEDED')
  const allowed: ReviewStatus[] = [
    'PENDING_CLOUD_ANALYSIS',
    'MANUAL_NEEDED',
    'AUDIT_REQUIRED',
    'AUTO_OK',
    'DONE',
    'REPORT_PENDING',
    'REPORT_CREATED',
    'INFERENCE_FAILED',
  ]
  // dashboard_api 프론트 status → MVP review_status
  const fromFront: Record<string, ReviewStatus> = {
    PROCESSING: 'PENDING_CLOUD_ANALYSIS',
    FAILED: 'INFERENCE_FAILED',
  }
  if (fromFront[s]) return fromFront[s]
  return (allowed.includes(s as ReviewStatus) ? s : 'MANUAL_NEEDED') as ReviewStatus
}

function asReportStatus(v: unknown): ReportStatus {
  const s = String(v || 'PENDING')
  // API reportStatus(프론트 매핑): PENDING | GENERATING | CREATED | FAILED
  if (s === 'CREATED') return 'GENERATED'
  if (s === 'NOT_CREATED') return 'PENDING'
  if (
    s === 'PENDING' ||
    s === 'GENERATING' ||
    s === 'GENERATED' ||
    s === 'COMPLETED' ||
    s === 'FAILED'
  ) {
    return s
  }
  return 'PENDING'
}

/** DynamoDB report.report_status 원값 → 프론트 */
function asDynamoReportStatus(v: unknown): ReportStatus {
  const s = String(v || 'NOT_CREATED')
  if (s === 'NOT_CREATED') return 'PENDING'
  if (s === 'PENDING') return 'GENERATING'
  if (s === 'CREATED') return 'GENERATED'
  if (s === 'FAILED') return 'FAILED'
  return asReportStatus(s)
}

function normalizeDetection(raw: Record<string, unknown>, idx: number): Detection {
  const boxRaw = raw.box as { x?: number; y?: number; width?: number; height?: number } | undefined
  let confidence = typeof raw.confidence === 'number' ? raw.confidence : 0
  if (confidence > 1) confidence = confidence / 100

  // API 가 YOLO 원본 bbox 만 내려줌. 없으면 빈 박스(확대/오버레이 안 함)
  const box = {
    x: boxRaw?.x ?? 0,
    y: boxRaw?.y ?? 0,
    width: boxRaw?.width ?? 0,
    height: boxRaw?.height ?? 0,
  }

  return {
    id: String(raw.id || `d${idx}`),
    label: String(raw.label || 'unknown'),
    confidence,
    severity: asRiskLevel(raw.severity),
    description: String(raw.description || ''),
    box,
  }
}

/** dashboard_api JSON → 원격 프론트 MVP Inspection */
export function toInspection(raw: Record<string, unknown>): Inspection {
  const detectionsRaw = Array.isArray(raw.detections) ? raw.detections : []
  const detections = detectionsRaw.map((d, i) =>
    normalizeDetection((d || {}) as Record<string, unknown>, i + 1),
  )
  const containerId = String(
    raw.container_id || raw.containerId || '-',
  )
  const eventId = String(raw.event_id || raw.id || '')
  const review =
    raw.review_status ||
    raw.status ||
    'MANUAL_NEEDED'

  const imageUrl = String(
    raw.raw_image_url ||
      raw.originalImage ||
      raw.image_s3_url ||
      '/placeholder.svg',
  )

  const damageSummary = (() => {
    const labels = [
      ...new Set(
        detections
          .map((d) => d.label?.trim())
          .filter((label): label is string => Boolean(label)),
      ),
    ]
    if (labels.length > 0) return labels.join(', ')
    const rawSummary = String(
      raw.damage_summary || raw.detectedDamage || '손상 정보 없음',
    )
    return [
      ...new Set(
        rawSummary
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    ].join(', ') || '손상 정보 없음'
  })()

  return {
    event_id: eventId,
    container_id: containerId,
    captured_at: String(raw.captured_at || raw.capturedAt || new Date().toISOString()),
    raw_image_url: imageUrl,
    annotated_s3_url:
      typeof raw.annotated_s3_url === 'string' ? raw.annotated_s3_url : undefined,
    image_s3_url: typeof raw.image_s3_url === 'string' ? raw.image_s3_url : imageUrl,
    risk_score:
      typeof raw.risk_score === 'number'
        ? raw.risk_score
        : typeof raw.riskScore === 'number'
          ? raw.riskScore
          : Number(raw.risk_score || raw.riskScore) || 0,
    risk_level: asRiskLevel(raw.risk_level || raw.riskLevel),
    review_status: asReviewStatus(review),
    damage_summary: damageSummary,
    detections,
    ocr: {
      text: containerId,
      confidence: 0.9,
      matches_manifest: true,
    },
    report_status: (() => {
      const nested = raw.report as
        | { reportStatus?: string; report_status?: string }
        | undefined
      const frontMapped = nested?.reportStatus || raw.reportStatus
      if (frontMapped != null && frontMapped !== '') {
        return asReportStatus(frontMapped)
      }
      return asDynamoReportStatus(nested?.report_status || raw.report_status)
    })(),
    report_created_at:
      (raw.report as { report_generated_at?: string } | undefined)?.report_generated_at ||
      (typeof raw.report_created_at === 'string' ? raw.report_created_at : undefined) ||
      (typeof raw.reportCreatedAt === 'string' ? raw.reportCreatedAt : undefined),
    report_url: (() => {
      const nested = raw.report as { reportUrl?: string; report_url?: string } | undefined
      const url =
        nested?.reportUrl ||
        nested?.report_url ||
        (typeof raw.reportUrl === 'string' ? raw.reportUrl : undefined) ||
        (typeof raw.report_url === 'string' ? raw.report_url : undefined)
      return url || undefined
    })(),
    report: (() => {
      const nested = raw.report as Record<string, unknown> | undefined
      if (!nested && !raw.reportUrl && !raw.report_url) return undefined
      const status = (() => {
        const frontMapped = nested?.reportStatus || raw.reportStatus
        if (frontMapped != null && frontMapped !== '') {
          return asReportStatus(frontMapped)
        }
        return asDynamoReportStatus(nested?.report_status || raw.report_status)
      })()
      const url =
        (typeof nested?.reportUrl === 'string' ? nested.reportUrl : undefined) ||
        (typeof nested?.report_url === 'string' ? nested.report_url : undefined) ||
        (typeof raw.reportUrl === 'string' ? raw.reportUrl : undefined) ||
        (typeof raw.report_url === 'string' ? raw.report_url : undefined)
      return {
        report_status: status,
        report_created_at:
          (typeof nested?.report_generated_at === 'string'
            ? nested.report_generated_at
            : undefined) || undefined,
        report_url: url,
        report_path:
          typeof nested?.report_path === 'string' ? nested.report_path : undefined,
        report_summary:
          typeof nested?.report_summary === 'string' ? nested.report_summary : undefined,
      }
    })(),
    assigned_inspector: String(
      raw.assigned_inspector || raw.inspector || '담당자 미지정',
    ),
    reviewer_comment:
      typeof raw.reviewer_comment === 'string'
        ? raw.reviewer_comment
        : typeof raw.reviewerComment === 'string'
          ? raw.reviewerComment
          : undefined,
    ai_summary: String(
      raw.ai_summary || raw.aiSummary || damageSummary || '',
    ),
    verdict: String(raw.verdict || ''),
    error_message:
      typeof raw.error_message === 'string'
        ? raw.error_message
        : typeof raw.errorMessage === 'string'
          ? raw.errorMessage
          : undefined,
  }
}

export async function listInspections(opts?: {
  keepImagesFrom?: Inspection[]
}): Promise<Inspection[]> {
  const kept = new Map((opts?.keepImagesFrom || []).map((i) => [i.event_id, i]))

  const results = await Promise.allSettled(
    LIST_STATUSES.map((status) =>
      api<{ items: Record<string, unknown>[]; count: number }>(
        `/inspections?status=${encodeURIComponent(status)}`,
      ),
    ),
  )

  const byId = new Map<string, Inspection>()
  for (const r of results) {
    if (r.status !== 'fulfilled') {
      console.warn('[listInspections]', r.reason)
      continue
    }
    for (const item of r.value.items || []) {
      const norm = toInspection(item)
      if (norm.event_id) byId.set(norm.event_id, norm)
    }
  }

  let items = Array.from(byId.values())
  items = await Promise.all(
    items.map(async (item) => {
      const prev = kept.get(item.event_id)
      const prevUrl = prev?.raw_image_url
      if (prevUrl && prevUrl !== '/placeholder.svg' && !prevUrl.startsWith('/containers/')) {
        return {
          ...item,
          raw_image_url: prevUrl,
          image_s3_url: prev.image_s3_url || prevUrl,
          annotated_s3_url: prev.annotated_s3_url,
          detections: prev.detections.length > 0 ? prev.detections : item.detections,
          ai_summary: item.ai_summary || prev.ai_summary,
          verdict: item.verdict || prev.verdict,
          ocr: prev.ocr,
        }
      }
      if (item.raw_image_url && item.raw_image_url !== '/placeholder.svg') {
        return item
      }
      try {
        return await getInspection(item.event_id)
      } catch (e) {
        console.warn('[listInspections] detail', item.event_id, e)
        return item
      }
    }),
  )
  return items
}

export async function getInspection(eventId: string): Promise<Inspection> {
  const raw = await api<Record<string, unknown>>(
    `/inspections/${encodeURIComponent(eventId)}`,
  )
  return toInspection(raw)
}

export async function reviewInspection(
  eventId: string,
  body: {
    action: 'approve' | 'modify' | 'reject'
    reviewer?: string
    memo?: string
    risk_level?: string
  },
): Promise<Inspection | null> {
  const res = await api<{
    item?: Record<string, unknown>
    deleted?: boolean
  }>(`/inspections/${encodeURIComponent(eventId)}/review`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (res.deleted || body.action === 'reject') return null
  if (res.item) return toInspection(res.item)
  return getInspection(eventId)
}

export function getApiBase() {
  return BASE
}

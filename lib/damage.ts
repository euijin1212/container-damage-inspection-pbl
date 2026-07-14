import type { Detection, Inspection } from './inspection-types'

/** 감지 손상 라벨 중복 제거 (rust, rust → rust) */
export function uniqueDamageLabels(
  damageSummary: string | undefined,
  detections: Detection[] = [],
): string {
  const fromDetections = [
    ...new Set(
      detections
        .map((d) => d.label?.trim())
        .filter((label): label is string => Boolean(label)),
    ),
  ]
  if (fromDetections.length > 0) return fromDetections.join(', ')

  const parts = (damageSummary || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  return [...new Set(parts)].join(', ') || '손상 정보 없음'
}

export function uniqueDamageFromInspection(inspection: Inspection): string {
  return uniqueDamageLabels(inspection.damage_summary, inspection.detections)
}

// Fixed inspection timestamps are formatted in UTC so server and client render
// identical strings (avoids hydration mismatches across timezones).

// "7월 13일 08:42"
export function formatCaptured(iso: string) {
  const d = new Date(iso)
  const month = d.getUTCMonth() + 1
  const day = d.getUTCDate()
  const hh = d.getUTCHours().toString().padStart(2, '0')
  const mm = d.getUTCMinutes().toString().padStart(2, '0')
  return `${month}월 ${day}일 ${hh}:${mm}`
}

// "2026. 7. 13. 오후 2:31"
export function formatDateTime(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('ko-KR', {
    timeZone: 'UTC',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

// "오후 2:31:05" — live header clock, rendered only after mount (client-side).
export function formatTimeOnly(iso: string) {
  const d = new Date(iso)
  return d.toLocaleString('ko-KR', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

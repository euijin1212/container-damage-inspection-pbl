'use client'

import { useEffect, useMemo, useRef } from 'react'
import { cn } from '@/lib/utils'
import type { BoundingBox, Detection } from '@/lib/inspection-types'

interface AnnotatedImageProps {
  src: string
  alt: string
  detections?: Detection[]
  activeId?: string | null
  annotated?: boolean
  /** 확대 중 사진 클릭 시 축소(선택 해제) */
  onClearActive?: () => void
}

function isValidBox(box?: BoundingBox | null): box is BoundingBox {
  return Boolean(box && box.width > 0.5 && box.height > 0.5)
}

/** 선택 bbox 가 화면의 ~70% 를 채우도록 확대 (중심 = bbox 중심) */
function zoomForBox(box: BoundingBox) {
  const scaleX = 70 / Math.max(box.width, 4)
  const scaleY = 70 / Math.max(box.height, 4)
  const scale = Math.min(Math.max(scaleX, scaleY), 4.5)
  return {
    scale,
    originX: box.x + box.width / 2,
    originY: box.y + box.height / 2,
  }
}

export function AnnotatedImage({
  src,
  alt,
  detections = [],
  activeId,
  annotated = true,
  onClearActive,
}: AnnotatedImageProps) {
  const frameRef = useRef<HTMLDivElement>(null)
  const active = useMemo(
    () => detections.find((d) => d.id === activeId) ?? null,
    [detections, activeId],
  )
  const activeBox = active && isValidBox(active.box) ? active.box : null
  const zoom = activeBox ? zoomForBox(activeBox) : null

  useEffect(() => {
    if (!activeId || !frameRef.current) return
    frameRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeId])

  return (
    <div
      ref={frameRef}
      className="relative aspect-[4/3] w-full overflow-hidden rounded-lg bg-slate-900"
    >
      <button
        type="button"
        disabled={!zoom}
        onClick={() => {
          if (zoom) onClearActive?.()
        }}
        className={cn(
          'block size-full border-0 bg-transparent p-0 text-left transition-transform duration-500 ease-out will-change-transform',
          zoom ? 'cursor-zoom-out' : 'cursor-default',
        )}
        style={{
          transform: zoom ? `scale(${zoom.scale})` : 'scale(1)',
          transformOrigin: zoom
            ? `${zoom.originX}% ${zoom.originY}%`
            : '50% 50%',
        }}
        aria-label={zoom ? '확대 해제' : alt}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src || '/placeholder.svg'}
          alt={alt}
          className="pointer-events-none size-full object-cover"
          draggable={false}
        />
      </button>

      {annotated && detections.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="rounded-md bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
            표시할 손상 구역이 없습니다
          </span>
        </div>
      )}

      {zoom && (
        <div className="pointer-events-none absolute bottom-2 left-2 rounded-md bg-black/55 px-2 py-1 text-[11px] text-slate-200">
          선택 손상 확대 중 · 사진을 누르면 축소
        </div>
      )}
    </div>
  )
}

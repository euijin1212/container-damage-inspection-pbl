'use client'

import { cn } from '@/lib/utils'
import type { Detection } from '@/lib/inspection-types'

const severityRing: Record<string, string> = {
  HIGH: 'border-destructive text-destructive',
  MEDIUM: 'border-warning text-warning',
  LOW: 'border-success text-success',
}

const severityBg: Record<string, string> = {
  HIGH: 'bg-destructive text-destructive-foreground',
  MEDIUM: 'bg-warning text-warning-foreground',
  LOW: 'bg-success text-success-foreground',
}

interface AnnotatedImageProps {
  src: string
  alt: string
  detections?: Detection[]
  activeId?: string | null
  annotated?: boolean
}

export function AnnotatedImage({ src, alt, detections = [], activeId, annotated = true }: AnnotatedImageProps) {
  return (
    <div className="relative aspect-[4/3] w-full overflow-hidden rounded-md border border-border bg-muted">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src || '/placeholder.svg'} alt={alt} className="size-full object-cover" crossOrigin="anonymous" />
      {annotated &&
        detections.map((d) => {
          const dim = activeId && activeId !== d.id
          return (
            <div
              key={d.id}
              className={cn(
                'absolute rounded-sm border-2 transition-opacity',
                severityRing[d.severity],
                dim ? 'opacity-25' : 'opacity-100',
              )}
              style={{
                left: `${d.box.x}%`,
                top: `${d.box.y}%`,
                width: `${d.box.width}%`,
                height: `${d.box.height}%`,
              }}
            >
              <span
                className={cn(
                  'absolute -top-px left-0 -translate-y-full whitespace-nowrap rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide',
                  severityBg[d.severity],
                )}
              >
                {d.label} · {Math.round(d.confidence * 100)}%
              </span>
            </div>
          )
        })}
      {annotated && detections.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="rounded-md border border-success/30 bg-success/15 px-3 py-1 font-mono text-xs uppercase tracking-wide text-success">
            No detections
          </span>
        </div>
      )}
    </div>
  )
}

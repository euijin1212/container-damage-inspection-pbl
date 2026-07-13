'use client'

import { useEffect, useState } from 'react'
import { Container, Loader2, Radio } from 'lucide-react'
import { formatTimeOnly } from '@/lib/format'

export function DashboardHeader({ processingCount }: { processingCount: number }) {
  const [now, setNow] = useState<string>('')

  useEffect(() => {
    const tick = () => setNow(formatTimeOnly(new Date().toISOString()))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-3 lg:px-6">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Container className="size-5" aria-hidden />
          </div>
          <div>
            <h1 className="text-sm font-semibold leading-tight tracking-tight">PortScan 관제 시스템</h1>
            <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">컨테이너 손상 검수</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="hidden items-center gap-1.5 rounded-md border border-info/30 bg-info/10 px-2.5 py-1 text-xs text-info sm:inline-flex">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            분석 중 {processingCount}건
          </span>
          <span className="hidden items-center gap-1.5 rounded-md border border-success/30 bg-success/10 px-2.5 py-1 text-xs text-success sm:inline-flex">
            <Radio className="size-3.5 animate-pulse" aria-hidden />
            실시간 연결됨 · 4터미널
          </span>
          <span className="flex flex-col items-end leading-tight">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">마지막 업데이트</span>
            <span className="font-mono text-sm tabular-nums text-foreground" aria-label="마지막 업데이트 시간">
              {now || '--:--:--'}
            </span>
          </span>
        </div>
      </div>
    </header>
  )
}

'use client'

import { useEffect, useState } from 'react'
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
    <header className="sticky top-0 z-40 border-b border-border/70 bg-card/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-6 px-6 py-5 lg:px-8">
        <div className="flex items-center">
          <div>
            <h1 className="text-lg font-bold leading-tight tracking-tight text-foreground">PortScan</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">컨테이너 AI 검수</p>
          </div>
        </div>

        <div className="text-right text-sm text-muted-foreground">
          <span>
            분석 중 {processingCount}건
          </span>
          <span className="mx-2 text-border">·</span>
          <span>실시간 연결됨</span>
          <span className="mx-2 text-border">·</span>
          <span aria-label="마지막 업데이트 시간">{now || '--:--:--'} 기준</span>
        </div>
      </div>
    </header>
  )
}

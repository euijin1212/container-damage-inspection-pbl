'use client'

import { useEffect, useState } from 'react'
import { Container, Radio } from 'lucide-react'
import { formatTimeOnly } from '@/lib/format'

export function DashboardHeader() {
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
            <h1 className="text-sm font-semibold leading-tight tracking-tight">PortScan Control</h1>
            <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
              Container Damage Inspection
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="hidden items-center gap-1.5 rounded-md border border-success/30 bg-success/10 px-2.5 py-1 text-xs text-success sm:inline-flex">
            <Radio className="size-3.5 animate-pulse" aria-hidden />
            Live · Terminal 4
          </span>
          <span className="font-mono text-sm tabular-nums text-muted-foreground" aria-label="Current time">
            {now || '--:--:--'}
          </span>
        </div>
      </div>
    </header>
  )
}

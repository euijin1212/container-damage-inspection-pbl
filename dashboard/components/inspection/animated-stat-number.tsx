'use client'

import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

interface AnimatedStatNumberProps {
  value: number
  className?: string
  accentClassName?: string
  duration?: number
}

export function AnimatedStatNumber({
  value,
  className,
  accentClassName = 'text-primary',
  duration = 420,
}: AnimatedStatNumberProps) {
  const previousValue = useRef(value)
  const [displayValue, setDisplayValue] = useState(value)
  const [accented, setAccented] = useState(false)

  useEffect(() => {
    const from = previousValue.current
    const to = value
    previousValue.current = value

    if (from === to) return

    const start = performance.now()
    setAccented(true)

    let frame = 0
    const tick = (now: number) => {
      const progress = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplayValue(Math.round(from + (to - from) * eased))

      if (progress < 1) {
        frame = requestAnimationFrame(tick)
      } else {
        setDisplayValue(to)
        window.setTimeout(() => setAccented(false), 220)
      }
    }

    frame = requestAnimationFrame(tick)

    return () => cancelAnimationFrame(frame)
  }, [duration, value])

  return (
    <span className={cn('transition-colors duration-300', accented ? accentClassName : className, !accented && className)}>
      {displayValue}
    </span>
  )
}

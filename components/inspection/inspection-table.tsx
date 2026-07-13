'use client'

import { useMemo, useState } from 'react'
import { ArrowUpRight, Search } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import type { Inspection, ReviewStatus, RiskLevel } from '@/lib/inspection-types'
import { STATUS_META } from '@/lib/mock-inspections'
import { RiskBadge, riskScoreColor, StatusBadge } from './status-badges'
import { formatCaptured } from '@/lib/format'

const RISK_ORDER: Record<RiskLevel, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 }

interface InspectionTableProps {
  inspections: Inspection[]
  onSelect: (inspection: Inspection) => void
}

export function InspectionTable({ inspections, onSelect }: InspectionTableProps) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<ReviewStatus | 'ALL'>('ALL')
  const [risk, setRisk] = useState<RiskLevel | 'ALL'>('ALL')

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return inspections
      .filter((i) => {
        if (status !== 'ALL' && i.status !== status) return false
        if (risk !== 'ALL' && i.riskLevel !== risk) return false
        if (!q) return true
        return (
          i.containerId.toLowerCase().includes(q) ||
          i.id.toLowerCase().includes(q) ||
          i.detectedDamage.toLowerCase().includes(q)
        )
      })
      .sort((a, b) => {
        // High-risk first, then by score, then newest.
        if (RISK_ORDER[a.riskLevel] !== RISK_ORDER[b.riskLevel]) {
          return RISK_ORDER[a.riskLevel] - RISK_ORDER[b.riskLevel]
        }
        if (b.riskScore !== a.riskScore) return b.riskScore - a.riskScore
        return new Date(b.capturedAt).getTime() - new Date(a.capturedAt).getTime()
      })
  }, [inspections, query, status, risk])

  return (
    <div className="rounded-lg border border-border bg-card">
      {/* Controls */}
      <div className="flex flex-col gap-3 border-b border-border p-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-sm font-medium">Inspection Queue</h2>
          <p className="text-xs text-muted-foreground">
            {rows.length} of {inspections.length} inspections · high-risk prioritized
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search container, ID, damage…"
              className="pl-8 sm:w-64"
              aria-label="Search inspections"
            />
          </div>
          <Select value={status} onValueChange={(v) => setStatus(v as ReviewStatus | 'ALL')}>
            <SelectTrigger className="sm:w-44" aria-label="Filter by status">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All statuses</SelectItem>
              {(Object.keys(STATUS_META) as ReviewStatus[]).map((s) => (
                <SelectItem key={s} value={s}>
                  {STATUS_META[s].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={risk} onValueChange={(v) => setRisk(v as RiskLevel | 'ALL')}>
            <SelectTrigger className="sm:w-32" aria-label="Filter by risk level">
              <SelectValue placeholder="Risk" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All risk</SelectItem>
              <SelectItem value="HIGH">High</SelectItem>
              <SelectItem value="MEDIUM">Medium</SelectItem>
              <SelectItem value="LOW">Low</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="whitespace-nowrap font-mono text-[11px] uppercase tracking-wider">Captured</TableHead>
              <TableHead className="whitespace-nowrap font-mono text-[11px] uppercase tracking-wider">Container ID</TableHead>
              <TableHead className="whitespace-nowrap font-mono text-[11px] uppercase tracking-wider">Detected Damage</TableHead>
              <TableHead className="whitespace-nowrap text-right font-mono text-[11px] uppercase tracking-wider">Risk</TableHead>
              <TableHead className="whitespace-nowrap font-mono text-[11px] uppercase tracking-wider">Level</TableHead>
              <TableHead className="whitespace-nowrap font-mono text-[11px] uppercase tracking-wider">Status</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((i) => (
              <TableRow
                key={i.id}
                className={cn(
                  'cursor-pointer',
                  i.riskLevel === 'HIGH' && 'bg-destructive/[0.04]',
                )}
                onClick={() => onSelect(i)}
              >
                <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                  {formatCaptured(i.capturedAt)}
                </TableCell>
                <TableCell className="whitespace-nowrap font-mono text-sm font-medium">{i.containerId}</TableCell>
                <TableCell className="max-w-[220px] truncate text-sm text-muted-foreground">{i.detectedDamage}</TableCell>
                <TableCell className="text-right">
                  <span className={cn('font-mono text-sm font-semibold tabular-nums', riskScoreColor(i.riskScore))}>
                    {i.riskScore}
                  </span>
                </TableCell>
                <TableCell>
                  <RiskBadge level={i.riskLevel} />
                </TableCell>
                <TableCell>
                  <StatusBadge status={i.status} />
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`View details for ${i.containerId}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      onSelect(i)
                    }}
                  >
                    <ArrowUpRight className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={7} className="py-10 text-center text-sm text-muted-foreground">
                  No inspections match the current filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

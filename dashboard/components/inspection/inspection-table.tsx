'use client'

import { useMemo, useState } from 'react'
import { AlertTriangle, ArrowUpRight, MoreHorizontal, RotateCw, Search, UserCog } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { Button, buttonVariants } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import type { Inspection, RiskLevel } from '@/lib/inspection-types'
import {
  type StatusFilter,
  FILTER_LABEL,
  getDisplayStatus,
  matchesStatusFilter,
} from '@/lib/status-filters'
import { riskScoreColor, StatusBadge } from './status-badges'
import { formatCaptured } from '@/lib/format'
import { uniqueDamageFromInspection } from '@/lib/damage'

// 드롭다운에 노출할 필터 (요약 카드 3종 + 세부 상태)
const STATUS_OPTIONS: StatusFilter[] = [
  'GATE_INFLOW',
  'DONE',
  'REPORT_CREATED',
]

type InspectionImageFields = {
  annotated_s3_url?: string
  image_s3_url?: string
  captured_at?: string
}

interface InspectionTableProps {
  inspections: Inspection[]
  selectedId?: string | null
  recentlyAddedIds?: Set<string>
  statusFilter: StatusFilter
  onStatusFilterChange: (filter: StatusFilter) => void
  onSelect: (inspection: Inspection) => void
  onRetry: (id: string) => void
  onManualSwitch: (id: string) => void
}

function getInspectionImage(inspection: Inspection) {
  const optional = inspection as Inspection & InspectionImageFields
  return optional.annotated_s3_url || optional.image_s3_url || inspection.raw_image_url || '/placeholder.svg'
}

function getCapturedAt(inspection: Inspection) {
  return (inspection as Inspection & InspectionImageFields).captured_at || inspection.captured_at
}

function rowAccentClass(inspection: Inspection) {
  if (inspection.review_status === 'MANUAL_NEEDED' && inspection.risk_level === 'HIGH') return 'border-l-destructive'
  if (inspection.review_status === 'AUDIT_REQUIRED') return 'border-l-warning'
  if (inspection.review_status === 'PENDING_CLOUD_ANALYSIS') return 'border-l-slate-300'
  return 'border-l-transparent'
}

function riskLabel(level: RiskLevel) {
  return { HIGH: '높음', MEDIUM: '보통', LOW: '낮음' }[level]
}

export function InspectionTable({
  inspections,
  selectedId,
  recentlyAddedIds,
  statusFilter,
  onStatusFilterChange,
  onSelect,
  onRetry,
  onManualSwitch,
}: InspectionTableProps) {
  const [query, setQuery] = useState('')
  const [risk, setRisk] = useState<RiskLevel | 'ALL'>('ALL')
  const [errorItem, setErrorItem] = useState<Inspection | null>(null)

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return inspections
      .filter((i) => {
        if (!matchesStatusFilter(i, statusFilter)) return false
        if (risk !== 'ALL' && i.risk_level !== risk) return false
        if (!q) return true
        return (
          i.container_id.toLowerCase().includes(q) ||
          i.event_id.toLowerCase().includes(q) ||
          uniqueDamageFromInspection(i).toLowerCase().includes(q) ||
          i.damage_summary.toLowerCase().includes(q)
        )
      })
      .sort(
        (a, b) =>
          new Date(a.captured_at).getTime() - new Date(b.captured_at).getTime(),
      )
  }, [inspections, query, statusFilter, risk])

  return (
    <div className="rounded-lg bg-card">
      {/* Controls */}
      <div className="flex flex-col gap-5 px-6 py-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight">검수 대기열</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            전체 {inspections.length}건 중 {rows.length}건 · 촬영 시간순(선입순)
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="컨테이너 번호, 검수 ID, 손상 검색"
              className="h-10 rounded-md border-input bg-background pl-8 text-sm sm:w-72"
              aria-label="검수 검색"
            />
          </div>
          <Select value={statusFilter} onValueChange={(v) => onStatusFilterChange(v as StatusFilter)}>
            <SelectTrigger className="h-10 rounded-md border-input bg-background sm:w-44" aria-label="상태 필터">
              <SelectValue placeholder="상태">
                {(v: unknown) => FILTER_LABEL[(v as StatusFilter) || 'ALL'] || String(v)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">전체</SelectItem>
              {STATUS_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  {FILTER_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={risk} onValueChange={(v) => setRisk(v as RiskLevel | 'ALL')}>
            <SelectTrigger className="h-10 rounded-md border-input bg-background sm:w-32" aria-label="위험도 필터">
              <SelectValue placeholder="위험도">
                {(v: unknown) =>
                  v === 'ALL' ? '전체 위험도' : { HIGH: '높음', MEDIUM: '보통', LOW: '낮음' }[v as RiskLevel]
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">전체 위험도</SelectItem>
              <SelectItem value="HIGH">높음</SelectItem>
              <SelectItem value="MEDIUM">보통</SelectItem>
              <SelectItem value="LOW">낮음</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto px-2 pb-3">
        <Table>
          <TableHeader>
            <TableRow className="border-b border-border/60 hover:bg-transparent">
              <TableHead className="w-[112px] whitespace-nowrap text-sm font-medium text-muted-foreground">이미지</TableHead>
              <TableHead className="whitespace-nowrap text-sm font-medium text-muted-foreground">컨테이너 번호</TableHead>
              <TableHead className="whitespace-nowrap text-sm font-medium text-muted-foreground">촬영 시간</TableHead>
              <TableHead className="whitespace-nowrap text-sm font-medium text-muted-foreground">감지 손상</TableHead>
              <TableHead className="whitespace-nowrap text-right text-sm font-medium text-muted-foreground">위험 점수</TableHead>
              <TableHead className="whitespace-nowrap text-sm font-medium text-muted-foreground">상태</TableHead>
              <TableHead className="whitespace-nowrap text-right text-sm font-medium text-muted-foreground">상세</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((i) => {
              const isProcessing = i.review_status === 'PENDING_CLOUD_ANALYSIS'
              const isFailed = i.review_status === 'INFERENCE_FAILED'
              const clickable = !isProcessing && !isFailed
              return (
                <TableRow
                  key={i.event_id}
                  className={cn(
                    'border-l-2 border-b-0 transition-colors hover:bg-primary/5',
                    rowAccentClass(i),
                    clickable && 'cursor-pointer',
                    i.event_id === selectedId && 'bg-primary/10',
                    recentlyAddedIds?.has(i.event_id) && 'inspection-row-arrive',
                    isProcessing && 'opacity-70',
                  )}
                  onClick={clickable ? () => onSelect(i) : undefined}
                >
                  <TableCell>
                    <div className="h-16 w-24 overflow-hidden rounded-md bg-muted">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={getInspectionImage(i)}
                        alt={`${i.container_id} 검수 썸네일`}
                        className="size-full object-cover"
                      />
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm font-bold text-foreground">
                    {i.container_id}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {formatCaptured(getCapturedAt(i))}
                  </TableCell>
                  <TableCell className="max-w-[220px] truncate text-sm text-muted-foreground">
                    {uniqueDamageFromInspection(i)}
                  </TableCell>
                  <TableCell className="text-right">
                    {isProcessing ? (
                      <span className="text-sm text-muted-foreground">-</span>
                    ) : (
                      <div>
                        <span className={cn('text-xl font-bold tabular-nums', riskScoreColor(i.risk_score))}>{i.risk_score}</span>
                        <span className="ml-1 text-xs text-muted-foreground">{riskLabel(i.risk_level)}</span>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge {...getDisplayStatus(i)} />
                  </TableCell>
                  <TableCell className="text-right">
                    {isFailed ? (
                      <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="outline"
                          size="sm"
                          className="border-destructive/40 text-destructive hover:bg-destructive/10"
                          onClick={() => setErrorItem(i)}
                        >
                          <AlertTriangle className="size-3.5" /> 오류 내용 확인
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            aria-label={`${i.container_id} 오류 작업`}
                            className={cn(buttonVariants({ variant: 'ghost', size: 'icon-sm' }))}
                          >
                            <MoreHorizontal className="size-4" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => onRetry(i.event_id)}>
                              <RotateCw className="size-4" /> 분석 재시도
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onManualSwitch(i.event_id)}>
                              <UserCog className="size-4" /> 수동 검수 전환
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    ) : (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={isProcessing}
                        aria-label={`${i.container_id} 상세 보기`}
                        onClick={(e) => {
                          e.stopPropagation()
                          onSelect(i)
                        }}
                      >
                        <ArrowUpRight className="size-4" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
            {rows.length === 0 && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={7} className="py-14 text-center">
                  <p className="text-sm font-medium text-foreground">
                    {statusFilter === 'ALL'
                      ? '현재 대기 중인 검수 항목이 없습니다.'
                      : '선택한 조건에 맞는 검수 항목이 없습니다.'}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {statusFilter === 'ALL'
                      ? '새로운 컨테이너 분석 결과가 들어오면 자동으로 표시됩니다.'
                      : '필터를 전체로 바꾸거나 다른 상태를 선택해 보세요.'}
                  </p>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* Error detail dialog */}
      <Dialog open={!!errorItem} onOpenChange={(o) => !o && setErrorItem(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-destructive" aria-hidden /> 처리 실패 상세
            </DialogTitle>
            <DialogDescription className="text-xs">
              {errorItem?.event_id} · {errorItem?.container_id}
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {errorItem?.error_message}
          </div>
          <DialogFooter className="gap-2 sm:justify-end">
            {errorItem && (
              <>
                <Button
                  variant="secondary"
                  onClick={() => {
                    onManualSwitch(errorItem.event_id)
                    setErrorItem(null)
                  }}
                >
                  <UserCog className="size-4" /> 수동 검수 전환
                </Button>
                <Button
                  onClick={() => {
                    onRetry(errorItem.event_id)
                    setErrorItem(null)
                  }}
                >
                  <RotateCw className="size-4" /> 분석 재시도
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

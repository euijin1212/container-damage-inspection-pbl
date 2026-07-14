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
import type { Inspection, ReviewStatus, RiskLevel } from '@/lib/inspection-types'
import { STATUS_META } from '@/lib/mock-inspections'
import { riskScoreColor, StatusBadge } from './status-badges'
import { formatCaptured } from '@/lib/format'

type StatusFilter = ReviewStatus | 'ALL'

// Lower number = higher priority (shown first).
const STATUS_PRIORITY: Record<ReviewStatus, number> = {
  MANUAL_NEEDED: 0,
  AUDIT_REQUIRED: 1,
  PROCESSING: 2,
  REPORT_PENDING: 3,
  FAILED: 4,
  REPORT_CREATED: 5,
  DONE: 6,
  AUTO_OK: 7,
}

// Order of the status dropdown options.
const STATUS_OPTIONS: ReviewStatus[] = [
  'PROCESSING',
  'MANUAL_NEEDED',
  'AUDIT_REQUIRED',
  'AUTO_OK',
  'DONE',
  'REPORT_PENDING',
  'REPORT_CREATED',
  'FAILED',
]

type InspectionImageFields = {
  annotated_s3_url?: string
  image_s3_url?: string
  captured_at?: string
}

interface InspectionTableProps {
  inspections: Inspection[]
  selectedId?: string | null
  statusFilter: StatusFilter
  onStatusFilterChange: (filter: StatusFilter) => void
  onSelect: (inspection: Inspection) => void
  onRetry: (id: string) => void
  onManualSwitch: (id: string) => void
}

function getInspectionImage(inspection: Inspection) {
  const optional = inspection as Inspection & InspectionImageFields
  return optional.annotated_s3_url || optional.image_s3_url || inspection.originalImage || '/placeholder.svg'
}

function getCapturedAt(inspection: Inspection) {
  return (inspection as Inspection & InspectionImageFields).captured_at || inspection.capturedAt
}

function getMockWaitTime(inspection: Inspection) {
  const captured = new Date(getCapturedAt(inspection)).getTime()
  if (Number.isNaN(captured)) return '-'
  const minutes = Math.max(1, Math.round((Date.now() - captured) / 60000))
  if (minutes < 60) return `${minutes}분`
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return remainder ? `${hours}시간 ${remainder}분` : `${hours}시간`
}

function rowAccentClass(inspection: Inspection) {
  if (inspection.status === 'MANUAL_NEEDED' && inspection.riskLevel === 'HIGH') return 'border-l-destructive'
  if (inspection.status === 'AUDIT_REQUIRED') return 'border-l-warning'
  if (inspection.status === 'PROCESSING') return 'border-l-slate-300'
  return 'border-l-transparent'
}

function riskLabel(level: RiskLevel) {
  return { HIGH: '높음', MEDIUM: '보통', LOW: '낮음' }[level]
}

export function InspectionTable({
  inspections,
  selectedId,
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
        if (statusFilter !== 'ALL' && i.status !== statusFilter) return false
        if (risk !== 'ALL' && i.riskLevel !== risk) return false
        if (!q) return true
        return (
          i.containerId.toLowerCase().includes(q) ||
          i.id.toLowerCase().includes(q) ||
          i.detectedDamage.toLowerCase().includes(q)
        )
      })
      .sort((a, b) => {
        // Manual review first, then random audit, then the rest.
        if (STATUS_PRIORITY[a.status] !== STATUS_PRIORITY[b.status]) {
          return STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status]
        }
        if (b.riskScore !== a.riskScore) return b.riskScore - a.riskScore
        return new Date(b.capturedAt).getTime() - new Date(a.capturedAt).getTime()
      })
  }, [inspections, query, statusFilter, risk])

  return (
    <div className="rounded-lg bg-card">
      {/* Controls */}
      <div className="flex flex-col gap-5 px-6 py-6 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight">검수 대기열</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            전체 {inspections.length}건 중 {rows.length}건 · 고위험 우선 정렬
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
                {(v: unknown) => (v === 'ALL' ? '전체' : STATUS_META[v as ReviewStatus].label)}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">전체</SelectItem>
              {STATUS_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  {STATUS_META[s].label}
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
              <TableHead className="whitespace-nowrap text-sm font-medium text-muted-foreground">대기 시간</TableHead>
              <TableHead className="whitespace-nowrap text-sm font-medium text-muted-foreground">감지 손상</TableHead>
              <TableHead className="whitespace-nowrap text-right text-sm font-medium text-muted-foreground">위험 점수</TableHead>
              <TableHead className="whitespace-nowrap text-sm font-medium text-muted-foreground">상태</TableHead>
              <TableHead className="whitespace-nowrap text-right text-sm font-medium text-muted-foreground">상세</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((i) => {
              const isProcessing = i.status === 'PROCESSING'
              const isFailed = i.status === 'FAILED'
              const clickable = !isProcessing && !isFailed
              return (
                <TableRow
                  key={i.id}
                  className={cn(
                    'border-l-2 border-b-0 transition-colors hover:bg-blue-50/50',
                    rowAccentClass(i),
                    clickable && 'cursor-pointer',
                    i.id === selectedId && 'bg-blue-50',
                    isProcessing && 'opacity-70',
                  )}
                  onClick={clickable ? () => onSelect(i) : undefined}
                >
                  <TableCell>
                    <div className="h-16 w-24 overflow-hidden rounded-md bg-muted">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={getInspectionImage(i)}
                        alt={`${i.containerId} 검수 썸네일`}
                        className="size-full object-cover"
                        crossOrigin="anonymous"
                      />
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm font-bold text-foreground">
                    {i.containerId}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {formatCaptured(getCapturedAt(i))}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {getMockWaitTime(i)}
                  </TableCell>
                  <TableCell className="max-w-[220px] truncate text-sm text-muted-foreground">{i.detectedDamage}</TableCell>
                  <TableCell className="text-right">
                    {isProcessing ? (
                      <span className="text-sm text-muted-foreground">-</span>
                    ) : (
                      <div>
                        <span className={cn('text-xl font-bold tabular-nums', riskScoreColor(i.riskScore))}>{i.riskScore}</span>
                        <span className="ml-1 text-xs text-muted-foreground">{riskLabel(i.riskLevel)}</span>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={i.status} />
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
                            aria-label={`${i.containerId} 오류 작업`}
                            className={cn(buttonVariants({ variant: 'ghost', size: 'icon-sm' }))}
                          >
                            <MoreHorizontal className="size-4" />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => onRetry(i.id)}>
                              <RotateCw className="size-4" /> 분석 재시도
                            </DropdownMenuItem>
                            <DropdownMenuItem onClick={() => onManualSwitch(i.id)}>
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
                        aria-label={`${i.containerId} 상세 보기`}
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
                <TableCell colSpan={8} className="py-14 text-center">
                  <p className="text-sm font-medium text-foreground">현재 대기 중인 검수 항목이 없습니다.</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    새로운 컨테이너 분석 결과가 들어오면 자동으로 표시됩니다.
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
              {errorItem?.id} · {errorItem?.containerId}
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {errorItem?.errorMessage}
          </div>
          <DialogFooter className="gap-2 sm:justify-end">
            {errorItem && (
              <>
                <Button
                  variant="secondary"
                  onClick={() => {
                    onManualSwitch(errorItem.id)
                    setErrorItem(null)
                  }}
                >
                  <UserCog className="size-4" /> 수동 검수 전환
                </Button>
                <Button
                  onClick={() => {
                    onRetry(errorItem.id)
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

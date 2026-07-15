'use client'

import { useEffect, useState } from 'react'
import {
  Check,
  Download,
  FileSearch,
  FileText,
  RefreshCw,
  RotateCw,
  ScanText,
  X,
} from 'lucide-react'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Progress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { Inspection } from '@/lib/inspection-types'
import { uniqueDamageFromInspection } from '@/lib/damage'
import { getInspection } from '@/lib/api'
import { getDisplayStatus, isApproved, isGateInflow } from '@/lib/status-filters'
import { SEVERITY_LABEL } from '@/lib/mock-inspections'
import { AnnotatedImage } from './annotated-image'
import { ReportBadge, RiskBadge, riskScoreColor, StatusBadge } from './status-badges'
import { formatCaptured, formatDateTime } from '@/lib/format'

type ConfirmType = 'approve' | 'reject' | 'reinspect' | null

interface InspectionDetailProps {
  inspection: Inspection | null
  open: boolean
  onOpenChange: (open: boolean) => void
  queueIndex: number
  queueTotal: number
  onApprove: (id: string) => void
  onReject: (id: string) => void
  onReinspect: (id: string, comment: string) => void | Promise<void>
  onGenerateReport: (id: string) => void
  /** 상세 재조회 후 상위 state 반영 (보고서 URL 등) */
  onRefreshDetail?: (inspection: Inspection) => void
}

const severityDot: Record<string, string> = {
  HIGH: 'bg-destructive',
  MEDIUM: 'bg-warning',
  LOW: 'bg-success',
}

export function InspectionDetail({
  inspection,
  open,
  onOpenChange,
  queueIndex,
  queueTotal,
  onApprove,
  onReject,
  onReinspect,
  onGenerateReport,
  onRefreshDetail,
}: InspectionDetailProps) {
  const [activeDetection, setActiveDetection] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmType>(null)
  const [comment, setComment] = useState('')
  const [actionBusy, setActionBusy] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [downloadNote, setDownloadNote] = useState(false)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  // Reset transient UI whenever the inspection changes.
  useEffect(() => {
    setActiveDetection(null)
    setConfirm(null)
    setComment('')
    setPreviewOpen(false)
    setDownloadNote(false)
    setReportLoading(false)
    setReportError(null)
    setPreviewUrl(null)
  }, [inspection?.event_id])

  useEffect(() => {
    if (!downloadNote) return
    const t = setTimeout(() => setDownloadNote(false), 2500)
    return () => clearTimeout(t)
  }, [downloadNote])

  if (!inspection) return null

  const report_status = inspection.report?.report_status ?? inspection.report_status ?? 'PENDING'
  const report_created_at = inspection.report?.report_created_at ?? inspection.report_created_at
  // 게이트 유입: 승인/반려/재검수. 승인 완료: 재검수만.
  const showReviewActions = isGateInflow(inspection) || isApproved(inspection)
  const showApproveReject = isGateInflow(inspection)
  const isAnalyzing = inspection.review_status === 'PENDING_CLOUD_ANALYSIS'

  async function resolveReportUrl(): Promise<string | null> {
    if (!inspection) return null
    const existing = inspection.report?.report_url ?? inspection.report_url
    if (existing) return existing

    setReportLoading(true)
    setReportError(null)
    try {
      const detail = await getInspection(inspection.event_id)
      onRefreshDetail?.(detail)
      const url = detail.report?.report_url ?? detail.report_url
      if (!url) {
        setReportError('S3 보고서 URL을 찾지 못했습니다. report_path 를 확인하세요.')
        return null
      }
      return url
    } catch (e) {
      setReportError(e instanceof Error ? e.message : String(e))
      return null
    } finally {
      setReportLoading(false)
    }
  }

  async function openReportPreview() {
    const url = await resolveReportUrl()
    if (url) {
      setPreviewUrl(url)
      setPreviewOpen(true)
    }
  }

  async function downloadReportPdf() {
    const url = await resolveReportUrl()
    if (!url) return
    window.open(url, '_blank', 'noopener,noreferrer')
    setDownloadNote(true)
  }

  function closeConfirm() {
    setConfirm(null)
    setComment('')
  }

  async function runConfirm() {
    if (!inspection || actionBusy) return
    if (confirm === 'approve') {
      onApprove(inspection.event_id)
      closeConfirm()
      return
    }
    if (confirm === 'reject') {
      onReject(inspection.event_id)
      closeConfirm()
      return
    }
    if (confirm === 'reinspect') {
      setActionBusy(true)
      try {
        await onReinspect(inspection.event_id, comment)
        closeConfirm()
      } catch {
        // 에러는 page 에서 banner 처리
      } finally {
        setActionBusy(false)
      }
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full flex-col gap-0 bg-slate-950 p-0 text-slate-100 sm:!max-w-2xl">
        <SheetHeader className="border-b border-white/10 bg-slate-950 p-6">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm text-slate-400">컨테이너</span>
            <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-slate-300">
              대기열 {queueIndex} / {queueTotal}
            </span>
          </div>
          <SheetTitle className="text-3xl font-bold tracking-tight text-white">{inspection.container_id}</SheetTitle>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-slate-400">
            <span>{formatCaptured(inspection.captured_at)}</span>
            <StatusBadge {...getDisplayStatus(inspection)} />
          </div>
          <div className="flex items-center gap-3">
            <span className={cn('text-4xl font-bold tabular-nums leading-none', riskScoreColor(inspection.risk_score))}>
              {inspection.risk_score}
            </span>
            <RiskBadge level={inspection.risk_level} />
          </div>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="space-y-6 p-5">
            {/* Images */}
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-200">AI 분석 이미지</h3>
              <AnnotatedImage
                src={inspection.annotated_s3_url || inspection.raw_image_url}
                alt={`${inspection.container_id} AI 분석 이미지`}
                detections={inspection.detections}
                activeId={activeDetection}
                onClearActive={() => setActiveDetection(null)}
              />
            </div>

            {/* AI reading panel */}
            <div className="rounded-lg bg-slate-900">
              <div className="border-b border-white/10 px-5 py-4">
                <h3 className="text-sm font-semibold text-slate-100">AI 판독 패널</h3>
              </div>
              <div className="grid gap-px bg-white/10 md:grid-cols-2">
                <InfoCell label="감지 손상" value={uniqueDamageFromInspection(inspection)} tone="dark" />
                <InfoCell label="심각도" value={SEVERITY_LABEL[inspection.risk_level]} tone="dark" />
                <div className="bg-slate-900 p-4 md:col-span-2">
                  <dt className="text-xs text-slate-400">OCR 결과</dt>
                  <dd className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-100">
                    <span className="inline-flex items-center gap-1.5">
                      <ScanText className="size-4 text-accent" aria-hidden />
                      {inspection.ocr.text || '인식 실패'}
                    </span>
                    <span className={cn('text-xs', inspection.ocr.matches_manifest ? 'text-success' : 'text-warning')}>
                      {inspection.ocr.matches_manifest ? 'Manifest 일치' : 'Manifest 확인 필요'}
                    </span>
                  </dd>
                </div>
              </div>
              <div className="border-t border-white/10 p-5">
                <p className="text-xs text-slate-400">AI 판단 근거</p>
                <p className="mt-2 text-sm leading-6 text-slate-300 text-pretty">
                  {inspection.ai_summary || 'AI 판독 요약이 아직 생성되지 않았습니다.'}
                </p>
              </div>
              <div className="border-t border-white/10 p-5">
                <div className="mb-2 flex items-center justify-between">
                  <h4 className="text-sm font-medium text-slate-300">
                    감지 결과 {inspection.detections.length}건
                  </h4>
                  <span className="text-xs text-slate-500">{inspection.event_id}</span>
                </div>
                <div className="space-y-2">
                {inspection.detections.length === 0 && (
                  <p className="rounded-md bg-white/5 p-3 text-sm text-slate-400">
                    모델이 감지한 손상이 없습니다.
                  </p>
                )}
                {inspection.detections.map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    onClick={() => {
                      setActiveDetection((prev) => (prev === d.id ? null : d.id))
                    }}
                    className={cn(
                      'w-full rounded-md bg-white/5 p-3 text-left transition-colors hover:bg-white/10',
                      activeDetection === d.id && 'bg-white/10 ring-1 ring-white/25',
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className={cn('size-2 rounded-full', severityDot[d.severity])} aria-hidden />
                        <p className="text-sm font-medium text-slate-100">{d.label}</p>
                      </div>
                      <span className="rounded-full bg-white/10 px-2 py-0.5 text-xs text-slate-300">
                        심각도 {SEVERITY_LABEL[d.severity]}
                      </span>
                    </div>
                    <p className="mt-1.5 pl-[18px] text-xs text-slate-400 text-pretty">{d.description}</p>
                  </button>
                ))}
                </div>
              </div>
            </div>

            {/* Capture info */}
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-300">촬영 정보</h3>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-white/10">
                <InfoCell label="촬영 시간" value={formatDateTime(inspection.captured_at)} tone="dark" />
                <InfoCell label="담당 검수자" value={inspection.assigned_inspector || '미배정'} tone="dark" />
              </dl>
            </div>

            {/* Report section */}
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-300">보고서 상태</h3>
              <div className="space-y-3 rounded-lg bg-slate-900 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <FileText className="size-5 text-slate-400" aria-hidden />
                    <div>
                      <ReportBadge status={report_status} />
                      <p className="mt-1 text-xs text-slate-400">
                        {report_status === 'GENERATED' || report_status === 'COMPLETED'
                          ? report_created_at
                            ? `생성 일시 ${formatDateTime(report_created_at)}`
                            : `EIR PDF 준비됨 · ${inspection.event_id}.pdf`
                          : report_status === 'GENERATING'
                            ? '검출 결과 · 이미지 · OCR 취합 중'
                            : report_status === 'FAILED'
                              ? '보고서 생성에 실패했습니다.'
                              : '아직 생성된 보고서가 없습니다.'}
                      </p>
                      {(report_status === 'GENERATED' || report_status === 'COMPLETED') &&
                        (inspection.verdict || inspection.ai_summary) && (
                          <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                            {inspection.verdict
                              ? `판정: ${inspection.verdict}`
                              : inspection.ai_summary}
                          </p>
                        )}
                    </div>
                  </div>
                  {report_status === 'PENDING' && (
                    <Button size="sm" onClick={() => onGenerateReport(inspection.event_id)}>
                      <FileText className="size-4" /> 보고서 생성
                    </Button>
                  )}
                  {report_status === 'FAILED' && (
                    <Button size="sm" variant="secondary" onClick={() => onGenerateReport(inspection.event_id)}>
                      <RotateCw className="size-4" /> 재생성
                    </Button>
                  )}
                </div>

                {report_status === 'GENERATING' && <Progress value={62} />}

                {(report_status === 'GENERATED' || report_status === 'COMPLETED') && (
                  <>
                    <Separator className="bg-white/10" />
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={reportLoading}
                        onClick={() => void openReportPreview()}
                      >
                        <FileSearch className="size-4" />
                        {reportLoading ? '불러오는 중…' : '보고서 미리보기'}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="border-white/20 bg-transparent text-slate-100 hover:bg-white/10 hover:text-white"
                        disabled={reportLoading}
                        onClick={() => void downloadReportPdf()}
                      >
                        <Download className="size-4" /> PDF 다운로드
                      </Button>
                      {downloadNote && (
                        <span className="text-xs text-blue-300">PDF 다운로드를 시작했습니다.</span>
                      )}
                    </div>
                    {reportError && (
                      <p className="text-xs text-destructive">{reportError}</p>
                    )}
                  </>
                )}

                {(report_status === 'PENDING' || report_status === 'GENERATING') && (
                  <div className="flex flex-wrap items-center gap-2 opacity-60">
                    <Button size="sm" variant="secondary" disabled>
                      <FileSearch className="size-4" /> 보고서 미리보기
                    </Button>
                    <Button size="sm" variant="outline" disabled>
                      <Download className="size-4" /> PDF 다운로드
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </ScrollArea>

        {/* Action footer — 승인 완료는 재검수만 */}
        {showReviewActions && (
          <div
            className={cn(
              'grid gap-2 border-t border-white/10 bg-slate-950 p-4',
              showApproveReject && !isAnalyzing ? 'grid-cols-1 sm:grid-cols-3' : 'grid-cols-1',
            )}
          >
            <Button variant="secondary" onClick={() => setConfirm('reinspect')}>
              <RefreshCw className="size-4" />
              {isAnalyzing ? '재분석 다시 시도' : '재검수 요청'}
            </Button>
            {showApproveReject && !isAnalyzing && (
              <>
                <Button
                  variant="outline"
                  className="border-destructive/40 text-destructive hover:bg-destructive/10"
                  onClick={() => setConfirm('reject')}
                >
                  <X className="size-4" /> 반려
                </Button>
                <Button
                  className="bg-success text-success-foreground hover:bg-success/90"
                  onClick={() => setConfirm('approve')}
                >
                  <Check className="size-4" /> 승인
                </Button>
              </>
            )}
          </div>
        )}
      </SheetContent>

      {/* Confirm dialogs */}
      <Dialog open={confirm !== null} onOpenChange={(o) => !o && closeConfirm()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirm === 'approve' && '검수 승인'}
              {confirm === 'reject' && '검수 반려'}
              {confirm === 'reinspect' && '재검수 요청'}
            </DialogTitle>
            <DialogDescription className="text-xs">
              {inspection.event_id} · {inspection.container_id}
            </DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {confirm === 'approve' &&
              '이 컨테이너 검수 건을 승인하시겠습니까? 승인 시 보고서가 자동 생성되며, 다음 검수 항목으로 이동합니다.'}
            {confirm === 'reject' &&
              '이 컨테이너 검수 건을 반려하시겠습니까? 관련 이미지·보고서(S3)와 검수 기록(DynamoDB)이 삭제됩니다.'}
            {confirm === 'reinspect' &&
              'Foundation Model이 이미지 화질을 개선한 뒤, 검수 의견을 반영해 손상을 다시 감지합니다. 최대 약 60초 걸릴 수 있습니다.'}
          </p>
          {confirm === 'reinspect' && (
            <Textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="재검수 시 AI에 전달할 검수 의견 (선택)"
              rows={3}
              disabled={actionBusy}
            />
          )}
          <DialogFooter className="gap-2 sm:justify-end">
            <Button variant="outline" onClick={closeConfirm} disabled={actionBusy}>
              취소
            </Button>
            <Button
              onClick={() => void runConfirm()}
              disabled={actionBusy}
              className={cn(
                confirm === 'approve' && 'bg-success text-success-foreground hover:bg-success/90',
                confirm === 'reject' && 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
              )}
            >
              {confirm === 'approve' && '승인'}
              {confirm === 'reject' && '반려'}
              {confirm === 'reinspect' && (actionBusy ? '재분석 중…' : '재검수 요청')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Report preview dialog — S3 Presigned PDF */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent className="flex max-h-[90vh] flex-col gap-0 overflow-hidden sm:!max-w-4xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="size-5 text-info" aria-hidden /> 컨테이너 손상 보고서
            </DialogTitle>
            <DialogDescription className="text-xs">
              {inspection.event_id} · {report_created_at ? formatDateTime(report_created_at) : ''}
            </DialogDescription>
          </DialogHeader>
          <div className="mt-3 min-h-0 flex-1 overflow-hidden rounded-md border border-border bg-muted/30">
            {previewUrl ? (
              <iframe
                title={`${inspection.event_id} 보고서 PDF`}
                src={previewUrl}
                className="h-[min(70vh,720px)] w-full"
              />
            ) : (
              <div className="flex h-[40vh] items-center justify-center p-6 text-sm text-muted-foreground">
                보고서 PDF URL이 없습니다.
              </div>
            )}
          </div>
          <DialogFooter className="mt-4 gap-2 sm:justify-end">
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>
              닫기
            </Button>
            {previewUrl && (
              <Button
                variant="secondary"
                onClick={() => window.open(previewUrl, '_blank', 'noopener,noreferrer')}
              >
                새 탭에서 열기
              </Button>
            )}
            <Button onClick={() => void downloadReportPdf()}>
              <Download className="size-4" /> PDF 다운로드
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Sheet>
  )
}

function InfoCell({
  label,
  value,
  mono,
  tone = 'light',
}: {
  label: string
  value: string
  mono?: boolean
  tone?: 'light' | 'dark'
}) {
  const dark = tone === 'dark'

  return (
    <div className={cn('p-4', dark ? 'bg-slate-900' : 'bg-card')}>
      <dt className={cn('text-xs', dark ? 'text-slate-400' : 'text-muted-foreground')}>{label}</dt>
      <dd className={cn('mt-1 text-sm', dark ? 'text-slate-100' : 'text-foreground', mono && 'font-medium')}>{value}</dd>
    </div>
  )
}
